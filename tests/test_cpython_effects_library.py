"""Every class in audioeffects builds a chain, and that chain renders.

This is the first time the library has had offline coverage at all. Half of it
is built on Dynamics and Splitter, which used to exist only inside a VST
plug-in's engine, so the only way to run those classes was to load the plug-in
in a host. Now they are ordinary audioif nodes and the whole catalogue renders
here.
"""

import math
import os
import sys
import unittest
from array import array

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (ROOT, os.path.join(ROOT, "lib")):
    if path not in sys.path:
        sys.path.insert(0, path)

import audiocore
import audioeffects
import audiofilters
import synthio
import audioinstruments

SAMPLE_RATE = 48000
audioeffects.configure(SAMPLE_RATE)

#: Every name the package exports as an effect.
CLASSES = tuple(sorted(
    name for name in dir(audioeffects)
    if not name.startswith("_") and isinstance(getattr(audioeffects, name), type)
))


#: The one class that cannot be built from a source alone.
EXTRA_ARGUMENTS = {"GraphicEQ": {"gains_db": (3.0, -2.0, 4.0, -1.0, 2.0)}}


def source(frames=4096, level=11000, rate=SAMPLE_RATE):
    """A stereo signal with content across the spectrum, loud enough to trip
    every threshold the library's defaults use."""
    values = array("h")
    for frame in range(frames):
        for channel in range(2):
            shape = ((frame * (61 + channel * 17)) % 401) - 200
            values.append(shape * level // 200)
    return audiocore.RawSample(values, sample_rate=rate, channel_count=2)


def build(name, **overrides):
    arguments = dict(EXTRA_ARGUMENTS.get(name, ()))
    arguments.update(overrides)
    return getattr(audioeffects, name)(source(), **arguments)


def peak(sample, blocks, skip=0):
    """Loudest sample over `blocks` buffers, after discarding `skip` of them.

    Skipping matters for anything with an envelope follower: the frames before
    its detector has risen pass through untouched, so a peak taken from the
    very start measures the attack transient rather than the effect.
    """
    loudest = 0
    for _ in range(skip):
        audiocore.get_buffer(sample)
    for _ in range(blocks):
        data = memoryview(bytes(audiocore.get_buffer(sample)[1])).cast("h")
        for value in data:
            loudest = max(loudest, -value if value < 0 else value)
    return loudest / 32768.0


def sine(hz, frames=40000, level=8000, rate=SAMPLE_RATE):
    """A stereo sine, long enough to outlast the skip in `rms`."""
    values = array("h")
    for frame in range(frames):
        value = int(level * math.sin(2.0 * math.pi * hz * frame / rate))
        values.append(value)
        values.append(value)
    return audiocore.RawSample(values, sample_rate=rate, channel_count=2)


def rms(sample, blocks=20, skip=8):
    total = 0
    count = 0
    for _ in range(skip):
        audiocore.get_buffer(sample)
    for _ in range(blocks):
        data = memoryview(bytes(audiocore.get_buffer(sample)[1])).cast("h")
        for value in data:
            total += value * value
            count += 1
    return math.sqrt(total / count) if count else 0.0


def tone_gain_db(hz, build_chain):
    """What `build_chain` does to a steady sine at `hz`, in dB. The dry
    reference is a second copy of the same sine measured the same way, so
    only the chain differs."""
    wet = rms(build_chain(sine(hz)))
    dry = rms(sine(hz))
    return 20.0 * math.log10(wet / dry)


def tilt_db(build_chain, high=16000.0, reference=1000.0):
    """How much darker or brighter `build_chain` leaves the top end, in dB
    relative to what it does at `reference`. A saturation curve costs a
    broadband decibel or so on its own, and that is level, not tone; the
    difference between the two frequencies is the tone."""
    return (tone_gain_db(high, build_chain)
            - tone_gain_db(reference, build_chain))


def spectrum(sample, blocks=20, skip=8):
    """Magnitude spectrum of the left channel, and the bin width, from a
    power-of-two window so no FFT padding is involved."""
    values = []
    for _ in range(skip):
        audiocore.get_buffer(sample)
    for _ in range(blocks):
        data = memoryview(bytes(audiocore.get_buffer(sample)[1])).cast("h")
        values.extend(data[0::2])
    size = 1
    while size * 2 <= len(values):
        size *= 2
    window = [0.5 - 0.5 * math.cos(2.0 * math.pi * i / size)
              for i in range(size)]
    real = [values[i] * window[i] for i in range(size)]
    imaginary = [0.0] * size
    _fft(real, imaginary)
    half = size // 2
    return ([math.hypot(real[i], imaginary[i]) for i in range(half)],
            SAMPLE_RATE / float(size))


def _fft(real, imaginary):
    """In-place radix-2 FFT. No numpy: these tests run wherever audioif
    builds, and the parity interpreters have no third-party packages."""
    size = len(real)
    j = 0
    for i in range(1, size):
        bit = size >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            real[i], real[j] = real[j], real[i]
            imaginary[i], imaginary[j] = imaginary[j], imaginary[i]
    length = 2
    while length <= size:
        angle = -2.0 * math.pi / length
        step_real, step_imaginary = math.cos(angle), math.sin(angle)
        for start in range(0, size, length):
            wr, wi = 1.0, 0.0
            for offset in range(length // 2):
                a, b = start + offset, start + offset + length // 2
                tr = real[b] * wr - imaginary[b] * wi
                ti = real[b] * wi + imaginary[b] * wr
                real[b], imaginary[b] = real[a] - tr, imaginary[a] - ti
                real[a], imaginary[a] = real[a] + tr, imaginary[a] + ti
                wr, wi = wr * step_real - wi * step_imaginary, \
                    wr * step_imaginary + wi * step_real
        length *= 2


def harmonic_db(build_chain, hz=1000.0, orders=(2, 3)):
    """Each named harmonic of `hz`, in dB relative to the fundamental."""
    magnitudes, bin_hz = spectrum(build_chain(sine(hz, frames=80000)))

    def peak_near(frequency):
        lo = max(0, int(frequency * 0.97 / bin_hz))
        hi = min(len(magnitudes), int(frequency * 1.03 / bin_hz) + 1)
        return max(magnitudes[lo:hi]) if hi > lo else 0.0

    base = peak_near(hz)
    out = []
    for order in orders:
        value = peak_near(hz * order)
        out.append(20.0 * math.log10(value / base)
                   if value > 0.0 and base > 0.0 else -200.0)
    return out


class EffectsLibraryTest(unittest.TestCase):
    def test_the_catalogue_is_all_there(self):
        self.assertEqual(len(CLASSES), 39, CLASSES)

    def test_every_effect_builds_and_renders(self):
        for name in CLASSES:
            effect = build(name)
            self.assertIsNotNone(effect.output, name)
            level = peak(effect.output, 8)
            self.assertGreater(level, 0.001, "%s renders silence" % name)

    def test_effects_chain_into_each_other(self):
        # The `.output` of one is the `source` of the next; that is the whole
        # composition rule, and the three here cover all three node kinds
        # (a plain effect, one built on a Splitter, one built on Dynamics).
        drive = audioeffects.Exciter(source(), frequency=2500.0, amount=0.4)
        comp = audioeffects.Compressor(drive.output, threshold_db=-30.0,
                                       ratio=6.0, character="optical")
        verb = audioeffects.Reverb(comp.output, preset="hall", mix=0.35)
        self.assertGreater(peak(verb.output, 12), 0.001)

    def test_an_instrument_feeds_an_effect(self):
        instrument = audioinstruments.create("tr909", SAMPLE_RATE)
        for note, _ in audioinstruments.load("tr909").NOTE_MAP[:4]:
            instrument.note_on(note)
        chain = audioeffects.TapeDelay(instrument.output, time_ms=220.0,
                                       feedback=0.4, mix=0.4)
        self.assertGreater(peak(chain.output, 12), 0.001)

    def test_configure_sets_the_rate_the_nodes_are_built_at(self):
        try:
            audioeffects.configure(22050)
            self.assertEqual(audioeffects.sample_rate(), 22050)
            slow = audioeffects.LowPass(source(rate=22050))
            self.assertEqual(slow.output.sample_rate, 22050)
        finally:
            audioeffects.configure(SAMPLE_RATE)
        self.assertEqual(audioeffects.LowPass(source()).output.sample_rate,
                         SAMPLE_RATE)

    def test_a_bell_lands_where_it_was_asked_for(self):
        # Pins both engine fixes at the library level. A peaking bell is
        # only usable once PEAKING_EQ computes b2 with the RBJ sign, and it
        # only lands on its own center once a stereo Filter stops sharing
        # one biquad state between the channels - with that sharing the
        # recursion advances twice per frame and every filter sits an
        # octave high. Measured, not merely rendered.
        for hz, expected in ((1000.0, 6.0), (250.0, 6.0)):
            at_center = tone_gain_db(
                hz, lambda s: audioeffects.ParametricEQ(
                    s, bands=[(hz, expected, 2.0)]).output)
            self.assertAlmostEqual(at_center, expected, delta=0.4,
                                   msg="bell at %g Hz" % hz)
            # Two octaves up the bell is over; a shared state would put the
            # boost here instead.
            away = tone_gain_db(
                hz * 4.0, lambda s: audioeffects.ParametricEQ(
                    s, bands=[(hz, expected, 2.0)]).output)
            self.assertLess(abs(away), 0.5, "bell at %g Hz leaks" % hz)

    def test_a_cut_and_a_boost_cost_the_same(self):
        # The old ParametricEQ synthesized boosts from Splitter branches and
        # capped them at three; cuts were notch sections. Now both are one
        # biquad in one cascade, so ten boosts build as readily as ten cuts.
        boosts = audioeffects.GraphicEQ(source(), gains_db=(6.0,) * 10)
        self.assertEqual(len(boosts.biquads), 10)
        self.assertFalse(hasattr(boosts, "splitter"))
        self.assertGreater(peak(boosts.output, 8), 0.001)

    def test_an_eq_with_nothing_to_do_is_a_wire(self):
        src = source()
        flat = audioeffects.GraphicEQ(src, gains_db=(0.0,) * 10)
        self.assertEqual(flat.biquads, [])
        self.assertIs(flat.output, src)

    def test_a_filter_above_nyquist_is_refused(self):
        # Silently folded coefficients used to be unreachable because every
        # frequency was halved on the way in.
        with self.assertRaises(ValueError):
            audioeffects.LowPass(source(), frequency=SAMPLE_RATE * 0.75)

    def test_a_filter_sits_at_its_corner_across_the_whole_band(self):
        # Nothing pinned this, which is how the biquads got away with being
        # unusable at both ends of the band for as long as they were. Q 0.707
        # is -3.01 dB at the corner by definition, so the assertion needs no
        # reference implementation to compare against.
        for hz in (50.0, 100.0, 200.0, 400.0, 1000.0, 4000.0, 12000.0,
                   18000.0, 22000.0):
            for name in ("LowPass", "HighPass"):
                with self.subTest(filter=name, hz=hz):
                    at_corner = tone_gain_db(
                        hz, lambda s, n=name, f=hz:
                        getattr(audioeffects, n)(s, frequency=f).output)
                    self.assertAlmostEqual(at_corner, -3.01, delta=0.25)

    def test_a_low_filter_passes_what_it_should_and_stops_what_it_should(self):
        # The failure this replaces was silent and total: coefficients in Q15
        # quantize to nonsense below a few hundred hertz, and a LowPass at
        # 100 Hz returned silence while a HighPass at 30 Hz returned about
        # 21 dB of noise. See docs/upstream-diff.md.
        passband = tone_gain_db(
            25.0, lambda s: audioeffects.LowPass(s, frequency=100.0).output)
        self.assertAlmostEqual(passband, 0.0, delta=0.25)
        stopband = tone_gain_db(
            800.0, lambda s: audioeffects.LowPass(s, frequency=100.0).output)
        self.assertLess(stopband, -30.0)
        for hz in (30.0, 60.0):
            with self.subTest(hz=hz):
                passband = tone_gain_db(
                    hz * 8.0,
                    lambda s, f=hz: audioeffects.HighPass(s, frequency=f).output)
                self.assertAlmostEqual(passband, 0.0, delta=0.25)

    def test_a_low_shelf_lifts_its_shelf_and_not_the_whole_band(self):
        # An 80 Hz LOW_SHELF asked for +1.5 dB used to lift everything below
        # it by +13.4 - the coefficients had nowhere near enough resolution to
        # describe a gentle shelf that low.
        def shelf(source_sample):
            node = audiofilters.Filter(
                filter=synthio.Biquad(
                    synthio.FilterMode.LOW_SHELF, 80.0, Q=0.707,
                    A=audioeffects._core.db_to_amplitude(1.5)),
                **audioeffects._core.pcm())
            node.play(source_sample)
            return node

        self.assertAlmostEqual(tone_gain_db(20.0, shelf), 1.5, delta=0.25)
        self.assertAlmostEqual(tone_gain_db(2000.0, shelf), 0.0, delta=0.25)

    def test_every_graphic_eq_band_lands_on_its_own_iso_centre(self):
        # The bottom three were the visible casualty of the Q15 floor: a +6 dB
        # request read +12.14, +6.96 and +3.07 dB at 31.5, 63 and 125 Hz.
        for index, band in enumerate(audioeffects.eq.ISO_BANDS):
            gains = [0.0] * len(audioeffects.eq.ISO_BANDS)
            gains[index] = 6.0
            with self.subTest(band=band):
                self.assertAlmostEqual(
                    tone_gain_db(band, lambda s, g=gains:
                                 audioeffects.GraphicEQ(s, g).output),
                    6.0, delta=0.25)

    def test_the_multiband_bands_add_back_up_to_a_wire(self):
        # Below every threshold none of the three compressors is doing
        # anything, so what comes out is purely the crossover sum.
        def idle(source_sample):
            return audioeffects.MultibandCompressor(
                source_sample, thresholds_db=(6.0, 6.0, 6.0)).output

        for hz in (40.0, 100.0, 200.0, 1000.0, 2000.0, 8000.0):
            with self.subTest(hz=hz):
                self.assertAlmostEqual(tone_gain_db(hz, idle), 0.0, delta=0.4)

    def test_the_saturation_characters_are_different_curves(self):
        # The three are not presets over one curve: tube runs the engine's
        # asymmetric OVERDRIVE, which generates even harmonics, and the
        # other two run its odd-symmetric WAVESHAPE, which generates none.
        # A 2nd harmonic is the whole difference between a valve and a
        # tape machine, so measure it rather than trusting the table.
        second = {}
        for character in ("tube", "tape", "console"):
            second[character], third = harmonic_db(
                lambda s, c=character: audioeffects.Saturation(
                    s, amount=1.0, character=c).output)
            self.assertGreater(third, -60.0,
                               "%s generates no harmonics at all" % character)
        self.assertGreater(second["tube"], second["tape"] + 40.0)
        self.assertGreater(second["tube"], second["console"] + 40.0)

    def test_the_saturation_characters_are_level_matched(self):
        # Switching character should change the colour and not the gain,
        # or an arrangement has to be re-balanced to audition one.
        levels = [tone_gain_db(1000.0, lambda s, c=c: audioeffects.Saturation(
            s, amount=1.0, character=c).output)
            for c in ("tube", "tape", "console")]
        self.assertLess(max(levels) - min(levels), 0.75, levels)

    def test_amount_scales_the_whole_character(self):
        # Including the tone shaping. A quarter of the way into tape should
        # be a quarter of its top-end loss, not all of it.
        full, quarter, none = (
            tilt_db(lambda s, a=a: audioeffects.Saturation(
                s, amount=a, character="tape").output)
            for a in (1.0, 0.25, 0.0))
        self.assertLess(full, -2.0)
        self.assertAlmostEqual(quarter, full * 0.25, delta=0.25)
        self.assertAlmostEqual(none, 0.0, delta=0.1)

    def test_tape_darkens_and_console_brightens(self):
        tape = tilt_db(lambda s: audioeffects.Saturation(
            s, amount=1.0, character="tape").output)
        console = tilt_db(lambda s: audioeffects.Saturation(
            s, amount=1.0, character="console").output)
        self.assertLess(tape, -2.0)
        self.assertGreater(console, 0.2)
        # tube shapes nothing: its character is entirely in the harmonics.
        self.assertAlmostEqual(
            tilt_db(lambda s: audioeffects.Saturation(
                s, amount=1.0, character="tube").output), 0.0, delta=0.2)

    def test_tape_has_a_head_bump_and_the_other_two_do_not(self):
        # The low end is the half of the tape character that only became
        # possible once the biquads could describe an 80 Hz shelf at all.
        for character, expected in (("tape", 1.43), ("tube", 0.0),
                                    ("console", 0.0)):
            with self.subTest(character=character):
                self.assertAlmostEqual(
                    tilt_db(lambda s, c=character: audioeffects.Saturation(
                        s, amount=1.0, character=c).output,
                        high=40.0, reference=1000.0),
                    expected, delta=0.2)

    def test_an_unknown_character_is_refused(self):
        with self.assertRaises(ValueError):
            audioeffects.Saturation(source(), character="transistor")

    def test_the_overdrive_knob_actually_drives(self):
        # OVERDRIVE mode ignores the engine node's own `drive` argument -
        # its curve is a fixed shape - so passing the knob straight through
        # left it inert. It is pre-gain into the curve now, with the level
        # put back after, so turning it up buys harmonics and not volume.
        harmonics = []
        for drive in (0.1, 0.4, 0.9):
            second, third = harmonic_db(
                lambda s, d=drive: audioeffects.Overdrive(
                    s, drive=d, mix=1.0).output)
            harmonics.append(second)
        self.assertEqual(harmonics, sorted(harmonics), harmonics)
        self.assertGreater(harmonics[-1], harmonics[0] + 6.0, harmonics)
        levels = [tone_gain_db(1000.0, lambda s, d=d: audioeffects.Overdrive(
            s, drive=d, mix=1.0).output) for d in (0.1, 0.4, 0.9)]
        self.assertLess(max(levels) - min(levels), 2.0, levels)

    def test_a_bitcrusher_can_be_asked_for_a_bit_depth(self):
        for bits in (4, 8, 12):
            self.assertEqual(audioeffects.Bitcrusher(source(),
                                                     bits=bits).bits, bits)
        # Fewer bits is a coarser quantizer, so a louder error against the
        # signal it came from - which is what "crushed" means.
        eight = peak(audioeffects.Bitcrusher(source(), bits=8).output, 8)
        four = peak(audioeffects.Bitcrusher(source(), bits=4).output, 8)
        self.assertNotAlmostEqual(eight, four, places=3)
        with self.assertRaises(ValueError):
            audioeffects.Bitcrusher(source(), bits=20)

    def test_an_octaver_reaches_two_octaves_either_way(self):
        deep = audioeffects.Octaver(source(), down=0.4, down2=0.4)
        self.assertEqual(deep.down2.semitones, -24.0)
        self.assertIsNone(deep.up)
        self.assertGreater(peak(deep.output, 12), 0.001)
        high = audioeffects.Octaver(source(), down=0.0, up=0.4, up2=0.4)
        self.assertEqual(high.up2.semitones, 24.0)
        self.assertIsNone(high.down)

    def test_an_octaver_builds_only_the_octaves_it_was_asked_for(self):
        # A Splitter fans out to four taps, so the dry signal plus three
        # octaves is the ceiling - and the default, one octave down, should
        # cost one shifter rather than four.
        one = audioeffects.Octaver(source())
        self.assertEqual(len(one.mixer.voice), 2)
        with self.assertRaises(ValueError):
            audioeffects.Octaver(source(), down=0.3, down2=0.3, up=0.3,
                                 up2=0.3)

    def test_the_compressor_actually_compresses(self):
        # Not just "it renders". The comparison is against a Compressor whose
        # threshold sits above the signal, so both sides are the same node
        # pulling the same blocks and only the gain computer differs.
        idle = audioeffects.Compressor(source(), threshold_db=6.0, ratio=12.0)
        working = audioeffects.Compressor(source(), threshold_db=-36.0,
                                          ratio=12.0, character="fet")
        self.assertLess(peak(working.output, 8, skip=4),
                        peak(idle.output, 8, skip=4) * 0.75)


if __name__ == "__main__":
    unittest.main()
