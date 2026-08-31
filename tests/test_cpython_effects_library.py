"""Every class in audioeffects builds a chain, and that chain renders.

This is the first time the library has had offline coverage at all. Half of it
is built on Dynamics and Splitter, which used to exist only inside a VST
plug-in's engine, so the only way to run those classes was to load the plug-in
in a host. Now they are ordinary audioif nodes and the whole catalogue renders
here.
"""

import math
import unittest
from array import array

import audiocore
import audioeffects
import audiofilters
import synthio
import audioinstruments
from tools.validate_metadata import validate_component, validate_effects

SAMPLE_RATE = 48000
audioeffects.configure(SAMPLE_RATE)

#: Every name the package exports as an effect.
CLASSES = tuple(sorted(
    name for name in dir(audioeffects)
    if not name.startswith("_") and isinstance(getattr(audioeffects, name), type)
))


#: Arguments a class needs beyond a source. GraphicEQ cannot be built without
#: its gains; ConvolutionReverb can, but its default second of stereo impulse
#: is 1.5 MB and the patch tests walk it once per patch -- a quarter second
#: proves the same things and keeps the suite quick.
EXTRA_ARGUMENTS = {
    "GraphicEQ": {"gains_db": (3.0, -2.0, 4.0, -1.0, 2.0)},
    "ConvolutionReverb": {"seconds": 0.25},
}

#: The classes that carry a patch surface. Optional, and most do not yet -
#: see audioeffects._core.Effect.
PATCHABLE = tuple(name for name in CLASSES
                  if getattr(audioeffects, name).MACRO_LABELS)


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


def burst(hz, on=2000, total=48000, level=9000, rate=SAMPLE_RATE):
    """A short tone and then silence, so a delay's repeats arrive one at a
    time and can be measured separately."""
    values = array("h")
    for frame in range(total):
        value = int(level * math.sin(2.0 * math.pi * hz * frame / rate)) \
            if frame < on else 0
        values.append(value)
        values.append(value)
    return audiocore.RawSample(values, sample_rate=rate, channel_count=2)


def channels(sample, blocks):
    """Both channels of `blocks` buffers, as two lists of samples."""
    left, right = [], []
    for _ in range(blocks):
        data = memoryview(bytes(audiocore.get_buffer(sample)[1])).cast("h")
        left.extend(data[0::2])
        right.extend(data[1::2])
    return left, right


def loudest_in(values, start, length):
    window = values[start:start + length]
    return max((-v if v < 0 else v) for v in window) if window else 0


class EffectsLibraryTest(unittest.TestCase):
    def test_every_public_effect_implements_the_factory_contract(self):
        validate_effects(audioeffects)
        for name in CLASSES:
            cls = getattr(audioeffects, name)
            self.assertTrue(callable(getattr(cls, "create", None)), name)
            effect = build(name)
            self.assertIsNotNone(effect.output, name)

    def test_factory_owns_the_sample_rate(self):
        original = audioeffects.sample_rate()
        try:
            effect = audioeffects.create("LowPass", source(rate=22050),
                                         22050)
            self.assertEqual(effect.output.sample_rate, 22050)
        finally:
            audioeffects.configure(original)

    def test_the_catalogue_is_all_there(self):
        self.assertEqual(len(CLASSES), 46, CLASSES)

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

    def test_lookahead_stops_a_limiter_overshooting_the_transient(self):
        # Without it the gain only starts coming down once the peak has
        # already been through, so the first cycle of every transient goes
        # over the ceiling. With it the detector is ahead of the audio.
        def peak_over(lookahead_ms):
            values = array("h")
            for frame in range(24000):
                loud = 1200 <= frame < 6000
                value = 32000 if loud and frame % 2 else (
                    -32000 if loud else 0)
                values.append(value)
                values.append(value)
            source = audiocore.RawSample(values, sample_rate=SAMPLE_RATE,
                                         channel_count=2)
            limiter = audioeffects.Limiter(source, ceiling_db=-12.0,
                                           release_ms=60.0,
                                           lookahead_ms=lookahead_ms)
            return peak(limiter.output, 60)

        ceiling = 10.0 ** (-12.0 / 20.0)
        self.assertGreater(peak_over(0.0), ceiling * 1.5)
        self.assertLess(peak_over(5.0), ceiling * 1.2)

    def test_true_peak_sees_the_level_between_the_samples(self):
        # A quarter-rate sine offset by 45 degrees puts every sample at
        # -3 dBFS and every actual peak, halfway between two of them, at 0.
        # A sample-peak detector cannot see that at all.
        def reduction(true_peak):
            values = array("h")
            for frame in range(12000):
                value = int(32767.0 * math.sin(
                    math.pi * frame / 2.0 + math.pi / 4.0))
                values.append(value)
                values.append(value)
            source = audiocore.RawSample(values, sample_rate=SAMPLE_RATE,
                                         channel_count=2)
            limiter = audioeffects.Limiter(source, ceiling_db=-2.0,
                                           true_peak=true_peak)
            for _ in range(20):
                audiocore.get_buffer(limiter.output)
            return limiter.node.gain_reduction_db()

        self.assertEqual(reduction(False), 0.0)
        self.assertLess(reduction(True), -0.3)

    def test_the_new_dynamics_options_are_off_by_default(self):
        # Everything built before this phase has to render exactly as it did,
        # which is why both are opt-in rather than sensible defaults.
        plain = audioeffects.Limiter(source())
        self.assertEqual(plain.macro(2), 0.0)
        self.assertLess(plain.macro(3), 0.5)

    def test_a_tape_delay_leaves_the_dry_path_alone(self):
        # It used not to. The tone filter sat after the delay's own dry/wet
        # blend, so at mix=0.14 a TapeDelay took 19 dB off 10 kHz and 33 dB
        # off 16 kHz of the signal that was supposed to pass straight
        # through. The filter is inside the feedback loop now.
        def chain(source):
            return audioeffects.TapeDelay(source, mix=0.14,
                                          feedback=0.0).output

        low = tone_gain_db(1000.0, chain)
        high = tone_gain_db(10000.0, chain)
        self.assertAlmostEqual(high, low, delta=0.5)

    def test_a_tape_delay_darkens_each_repeat_more_than_the_last(self):
        # The point of putting the filter in the loop: a repeat passes
        # through it once per lap, so the third is darker than the first.
        # Measured as how much of each tone survives three laps.
        def survival(hz):
            delay = audioeffects.TapeDelay(burst(hz), time_ms=100.0,
                                           feedback=0.7, mix=1.0, wow=0.0,
                                           tone_hz=3000.0, drive=0.0)
            left, _ = channels(delay.output, 200)
            step = int(0.1 * SAMPLE_RATE)
            first = loudest_in(left, step, 2000)
            third = loudest_in(left, step * 3, 2000)
            self.assertGreater(first, 0)
            return third / float(first)

        self.assertLess(survival(8000.0), survival(500.0) * 0.5)

    def test_ping_pong_repeats_alternate_between_the_channels(self):
        # Two delays panned apart, which is what this used to be, puts a
        # repeat on both sides at once. Alternation needs each channel's
        # output in the other channel's line.
        delay = audioeffects.PingPongDelay(burst(1000.0, on=400),
                                           time_ms=100.0, feedback=0.7,
                                           mix=1.0, tone_hz=16000.0)
        left, right = channels(delay.output, 200)
        step = int(0.1 * SAMPLE_RATE)
        sides = [(loudest_in(left, step * n, 800),
                  loudest_in(right, step * n, 800)) for n in range(1, 5)]
        for index, (on_left, on_right) in enumerate(sides):
            if index % 2 == 0:
                self.assertGreater(on_left, on_right * 8 + 1, sides)
            else:
                self.assertGreater(on_right, on_left * 8 + 1, sides)

    def test_an_older_analog_delay_is_darker_and_narrower(self):
        # `age` is one knob over the loop's low-pass, its high-pass and its
        # drift. Only the first two are measurable as a level.
        def repeat_level(hz, age):
            delay = audioeffects.AnalogDelay(burst(hz), time_ms=100.0,
                                             feedback=0.6, mix=1.0, age=age,
                                             drive=0.0)
            left, _ = channels(delay.output, 200)
            return loudest_in(left, int(0.2 * SAMPLE_RATE), 2000)

        self.assertLess(repeat_level(6000.0, 1.0), repeat_level(6000.0, 0.0))
        self.assertLess(repeat_level(80.0, 1.0), repeat_level(80.0, 0.0))

    def test_a_delay_line_can_be_emptied(self):
        delay = audioeffects.TapeDelay(burst(1000.0), time_ms=100.0,
                                        feedback=0.8, mix=1.0)
        channels(delay.output, 40)
        delay.clear()
        self.assertEqual(peak(delay.output, 4), 0.0)

    def test_a_ring_modulator_makes_sidebands_and_keeps_neither_original(
            self):
        # The definition of ring modulation, and the thing no LFO can do: a
        # 1 kHz tone against a 220 Hz carrier comes back as 780 and 1220 and
        # nothing at 1000. A Tremolo at the same settings would keep the
        # 1 kHz and could not reach 220 Hz in the first place.
        effect = audioeffects.RingMod(sine(1000.0, frames=80000),
                                      frequency=220.0)
        # The carrier table holds a whole number of cycles, so it lands a
        # fraction of a hertz off what was asked for; the sidebands are around
        # what it actually is, not around 220.
        carrier = effect.macro(0)
        magnitudes, bin_hz = spectrum(effect.output)

        def peak_near(frequency):
            lo = max(0, int(frequency * 0.97 / bin_hz))
            hi = min(len(magnitudes), int(frequency * 1.03 / bin_hz) + 1)
            return max(magnitudes[lo:hi]) if hi > lo else 0.0

        lower = peak_near(1000.0 - carrier)
        upper = peak_near(1000.0 + carrier)
        self.assertGreater(lower, 0.0)
        self.assertAlmostEqual(20.0 * math.log10(upper / lower), 0.0, delta=1.5)
        self.assertLess(20.0 * math.log10(peak_near(1000.0) / lower), -25.0)
        self.assertLess(20.0 * math.log10(peak_near(carrier) / lower), -25.0)

    def test_a_ring_modulator_at_zero_depth_is_a_wire(self):
        # Depth folds into the carrier table rather than being a second
        # multiply, so zero depth has to come out as a constant carrier -
        # which is the one setting that proves the table is built the way the
        # docstring says it is.
        self.assertAlmostEqual(
            tone_gain_db(1000.0,
                         lambda s: audioeffects.RingMod(s, depth=0.0).output),
            0.0, delta=0.05)
        self.assertAlmostEqual(
            tone_gain_db(1000.0,
                         lambda s: audioeffects.RingMod(s, mix=0.0).output),
            0.0, delta=0.05)

    def test_patch_zero_is_the_constructor_defaults(self):
        # Patch 0 is defined as the defaults rendered onto the 7-bit grid, so
        # this catches a default that moves without its patch following it.
        for name in PATCHABLE:
            effect = build(name)
            expected = tuple(
                int(round(position * 127)) for position in effect._macros)
            self.assertEqual(getattr(audioeffects, name).PATCHES[0][1],
                             expected, name)

    def test_every_patch_names_a_value_for_every_macro(self):
        for name in PATCHABLE:
            cls = getattr(audioeffects, name)
            for index, (patch_name, values) in sorted(cls.PATCHES.items()):
                self.assertEqual(len(values), len(cls.MACRO_LABELS),
                                 "%s patch %d" % (name, index))
                self.assertTrue(patch_name, "%s patch %d" % (name, index))
                for value in values:
                    self.assertIsInstance(value, int)
                    self.assertTrue(0 <= value <= 127,
                                    "%s patch %d" % (name, index))

    def test_every_patch_builds_and_renders(self):
        for name in PATCHABLE:
            for index in sorted(getattr(audioeffects, name).PATCHES):
                effect = build(name, patch=index)
                self.assertGreater(peak(effect.output, 8), 0.001,
                                   "%s patch %d renders silence"
                                   % (name, index))

    def test_a_macro_moves_the_thing_it_names(self):
        effect = build(PATCHABLE[0])
        for index, span in enumerate(effect._MACRO_RANGES):
            effect.set_macro(index, 127)
            self.assertAlmostEqual(effect.macro(index), span[1], delta=1e-6)
            effect.set_macro(index, 0)
            self.assertAlmostEqual(effect.macro(index), span[0], delta=1e-6)

    def test_a_macro_index_the_class_does_not_have_is_refused(self):
        # Loud, unlike an unknown program change: a host addressing a knob
        # that is not there is an application bug, not a wire message.
        effect = build(PATCHABLE[0])
        with self.assertRaises(IndexError):
            effect.set_macro(len(effect.MACRO_LABELS), 64)

    def test_a_program_change_to_a_patch_that_is_not_there_is_ignored(self):
        effect = build(PATCHABLE[0])
        before = list(effect._macros)
        effect.program_change(99)
        self.assertEqual(effect._macros, before)

    def test_a_class_without_macros_declares_an_empty_macro_surface(self):
        plain = audioeffects.Reverb(source())
        self.assertEqual(plain.MACRO_LABELS, ())
        self.assertEqual(plain.MACRO_MODES, {})
        self.assertEqual(plain.PATCHES, {0: ("Default", ())})
        with self.assertRaises(IndexError):
            plain.set_macro(0, 64)

    def test_the_compressor_actually_compresses(self):
        # Not just "it renders". The comparison is against a Compressor whose
        # threshold sits above the signal, so both sides are the same node
        # pulling the same blocks and only the gain computer differs.
        idle = audioeffects.Compressor(source(), threshold_db=6.0, ratio=12.0)
        working = audioeffects.Compressor(source(), threshold_db=-36.0,
                                          ratio=12.0, character="fet")
        self.assertLess(peak(working.output, 8, skip=4),
                        peak(idle.output, 8, skip=4) * 0.75)

    # --- convolution -----------------------------------------------------

    def test_a_convolver_actually_convolves(self):
        # The claim is arithmetic, so check it against the arithmetic: a
        # three-tap impulse against a sine has to give the sine plus two
        # delayed, scaled copies of it, sample for sample.
        import audioconvolve
        taps = array("h", [0] * 700)
        taps[0], taps[300], taps[650] = 32767, 16000, -8000
        level, hz = 6000, 440.0
        values = array("h")
        for frame in range(4096):
            value = int(level * math.sin(2.0 * math.pi * hz * frame
                                         / SAMPLE_RATE))
            values.append(value)
            values.append(value)
        node = audioconvolve.Convolver(impulse=taps, max_taps=1024, mix=1.0)
        node.play(audiocore.RawSample(values, sample_rate=SAMPLE_RATE,
                                      channel_count=2))
        rendered = []
        for _ in range(6):
            rendered.extend(
                memoryview(bytes(audiocore.get_buffer(node)[1])).cast("h")[0::2])

        latency = audioconvolve.FRAMES
        worst = 0.0
        for index in range(latency, len(rendered)):
            expected = 0.0
            for offset, gain in ((0, 32767), (300, 16000), (650, -8000)):
                position = index - latency - offset
                if 0 <= position < len(values) // 2:
                    expected += (level * math.sin(2.0 * math.pi * hz * position
                                                  / SAMPLE_RATE)
                                 * gain / 32768.0)
            worst = max(worst, abs(rendered[index] - expected))
        # The gains sum to 1.73, so a source quantized to whole int16 steps
        # can be that far out on its own before the convolution adds anything.
        self.assertLess(worst, 2.5)

    def test_a_convolver_with_no_impulse_is_a_wire(self):
        # And a wire with no latency: a chain built before its impulse
        # arrives must not drift against its neighbours. Compared against the
        # source's own values rather than a second RawSample, because a
        # RawSample hands back its whole buffer per pull and the convolver
        # hands back 256 frames.
        import audioconvolve
        node = audioconvolve.Convolver(max_taps=512)
        node.play(source())
        self.assertEqual(node.taps, 0)
        rendered = []
        for _ in range(4):
            rendered.extend(
                memoryview(bytes(audiocore.get_buffer(node)[1])).cast("h"))
        expected = list(memoryview(
            bytes(audiocore.get_buffer(source())[1])).cast("h"))
        self.assertEqual(rendered, expected[:len(rendered)])

    def test_an_impulse_longer_than_the_convolver_is_refused(self):
        # Not truncated. The capacity was chosen at construction and
        # something downstream may already be pulling.
        import audioconvolve
        node = audioconvolve.Convolver(max_taps=256)
        with self.assertRaises(ValueError):
            node.load(array("h", [0] * 4000), 1)

    def test_a_synthesized_room_decays_at_the_time_it_was_asked_for(self):
        verb = audioeffects.ConvolutionReverb(source(), seconds=0.5)
        verb.set_macro(4, 127)          # full wet, so only the tail is measured
        low, high = audioeffects.ConvolutionReverb._MACRO_RANGES[0][:2]
        for knob in (127, 64, 0):
            verb.set_macro(0, knob)
            expected = 0.5 * (low + (high - low) * knob / 127.0)
            self.assertAlmostEqual(verb.decay_seconds, expected, delta=1e-9)

    def test_a_synthesized_room_is_not_the_same_noise_on_both_sides(self):
        # A stereo impulse whose channels agreed would be a mono impulse, and
        # the whole reason to spend twice the memory is that they do not.
        verb = audioeffects.ConvolutionReverb(source(), seconds=0.25,
                                              stereo=True)
        verb.set_macro(4, 127)
        left, right = [], []
        for _ in range(12):
            data = memoryview(bytes(audiocore.get_buffer(verb.output)[1])).cast("h")
            left.extend(data[0::2])
            right.extend(data[1::2])
        window = slice(len(left) // 2, None)
        a, b = left[window], right[window]
        mean_a = sum(a) / len(a)
        mean_b = sum(b) / len(b)
        covariance = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
        spread_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
        spread_b = math.sqrt(sum((y - mean_b) ** 2 for y in b))
        correlation = covariance / (spread_a * spread_b)
        self.assertLess(abs(correlation), 0.25)

    def test_a_synthesized_room_is_normalized_rather_than_clipped(self):
        # An unnormalized tail of unit-amplitude noise is tens of thousands
        # of times the input. This is the check that the energy scaling in
        # audioif_convolve_synthesize is doing its job.
        verb = audioeffects.ConvolutionReverb(source(), seconds=0.5)
        verb.set_macro(4, 127)
        self.assertLess(peak(verb.output, 12, skip=2), 0.95)

    def test_a_cabinet_rolls_the_top_off_and_keeps_the_body(self):
        cabinet = lambda s: audioeffects.CabinetSim(s, patch=1).output
        body = tone_gain_db(100.0, cabinet)
        middle = tone_gain_db(1000.0, cabinet)
        top = tone_gain_db(10000.0, cabinet)
        # The bump is real, and the roll-off above the cone's limit is steep.
        self.assertGreater(body, middle + 2.0)
        self.assertLess(top, middle - 20.0)

    def test_a_cabinet_does_not_amplify(self):
        # It is normalized by what it does to a signal, not by its tallest
        # tap: three filter sections with two peaking boosts have a peak gain
        # of several, and a cabinet that multiplies by several clips.
        for index in sorted(audioeffects.CabinetSim.PATCHES):
            cabinet = audioeffects.CabinetSim(source(), patch=index)
            self.assertLess(peak(cabinet.output, 8, skip=2), 0.95, index)

    def test_the_transform_inverts_itself(self):
        # The FFT underneath all of this is not exposed, so it is exercised
        # here: a convolver loaded with a unit impulse is a forward transform
        # and an inverse transform with a multiply by one in between, and has
        # to hand back exactly what it was given.
        import audioconvolve
        unit = array("h", [0] * 256)
        unit[0] = 32767
        node = audioconvolve.Convolver(impulse=unit, max_taps=256, mix=1.0)
        node.play(source())
        latency = audioconvolve.FRAMES
        rendered = []
        for _ in range(5):
            rendered.extend(
                memoryview(bytes(audiocore.get_buffer(node)[1])).cast("h"))
        expected = list(memoryview(
            bytes(audiocore.get_buffer(source())[1])).cast("h"))
        worst = max(abs(a - b) for a, b in
                    zip(rendered[latency * 2:], expected))
        # 32767/32768 of the input, plus rounding: one step, never two.
        self.assertLessEqual(worst, 1)


class RackTest(unittest.TestCase):
    """The rack kind: one component whose graph is several effects.

    Ported from micropython-vst3's soundtrack racks; the mechanism is
    `audioeffects.Rack` and the two shared presets are `ShimmerHall` and
    `AirSpace`. A rack has exactly the effect shape, so everything the
    catalogue-wide tests assert already covers these three classes - what
    is here is the rack-specific behavior.
    """

    CHAIN = (("Overdrive", {"drive": 0.3, "mix": 0.4}),
             ("Reverb", {"preset": "plate", "mix": 0.25}))

    def test_a_chain_spec_builds_children_in_order_and_renders(self):
        rack = audioeffects.create("Rack", source(), SAMPLE_RATE,
                                   chain=self.CHAIN)
        self.assertEqual([type(child).__name__ for child in rack.effects],
                         ["Overdrive", "Reverb"])
        # Each child is fed the previous one's output, and the rack's
        # output is the last child's.
        self.assertIs(rack.effects[1]._source, rack.effects[0].output)
        self.assertIs(rack.output, rack.effects[1].output)
        self.assertGreater(peak(rack.output, 8), 0.001)

    def test_a_bare_name_is_a_valid_chain_entry(self):
        rack = audioeffects.Rack(source(), chain=("Saturation", "Reverb"))
        self.assertEqual(len(rack.effects), 2)
        self.assertGreater(peak(rack.output, 8), 0.001)

    def test_an_empty_rack_is_a_wire(self):
        src = source()
        rack = audioeffects.create("Rack", src, SAMPLE_RATE)
        self.assertIs(rack.output, src)
        self.assertEqual(rack.latency_samples, 0)
        self.assertEqual(rack.tail_samples, 0)
        self.assertGreater(peak(rack.output, 8), 0.001)

    def test_a_malformed_chain_entry_is_refused(self):
        with self.assertRaises(ValueError):
            audioeffects.Rack(source(), chain=(42,))
        with self.assertRaises(ImportError):
            audioeffects.Rack(source(), chain=("NoSuchEffect",))

    def test_racks_nest(self):
        # "Racks may contain and be used by other racks" - both directions.
        inner = ("Rack", {"chain": (("Saturation", {"amount": 0.2}),)})
        outer = audioeffects.Rack(source(), chain=(
            inner, ("Reverb", {"preset": "room", "mix": 0.2})))
        self.assertEqual(type(outer.effects[0]).__name__, "Rack")
        self.assertGreater(peak(outer.output, 8), 0.001)

    def test_latency_and_tail_are_the_whole_graph(self):
        rack = audioeffects.Rack(source(), chain=self.CHAIN)
        self.assertEqual(rack.latency_samples,
                         sum(child.latency_samples
                             for child in rack.effects))
        # No shipped effect bounds its tail yet, so one unknown child tail
        # makes the graph's unknown; the empty-rack test pins the finite
        # case at zero.
        self.assertIsNone(rack.tail_samples)

    def test_deinit_releases_the_children_but_not_the_source(self):
        src = source()
        rack = audioeffects.Rack(src, chain=self.CHAIN)
        children = list(rack.effects)
        rack.deinit()
        rack.deinit()
        with self.assertRaises(RuntimeError):
            _ = rack.output
        for child in children:
            with self.assertRaises(RuntimeError):
                _ = child.output
        # The borrowed source is still a live sample.
        self.assertGreater(peak(src, 2), 0.001)

    def test_rack_metadata_is_valid_component_metadata(self):
        from audioeffects import rack as module
        for cls in (audioeffects.Rack, audioeffects.ShimmerHall,
                    audioeffects.AirSpace):
            validate_component(cls, kind="effect",
                               expected_name=cls.__name__,
                               vendor_owner=module)

    def test_a_preset_rack_macro_moves_its_child(self):
        rack = audioeffects.ShimmerHall(source())
        self.assertEqual(rack.patch_index, 0)
        rack.set_macro(0, 0)
        self.assertEqual(rack.octave.mixer.voice[1].level, 0.0)
        self.assertIsNone(rack.patch_index)
        rack.set_macro(2, 127)
        self.assertAlmostEqual(rack.hall.node.mix, 0.7, delta=1e-6)
        rack.program_change(0)
        self.assertEqual(rack.patch_index, 0)
        self.assertAlmostEqual(rack.octave.mixer.voice[1].level,
                               70 / 127, delta=1e-6)

    def test_the_preset_racks_chain_audio_through_their_children(self):
        for name in ("ShimmerHall", "AirSpace"):
            rack = getattr(audioeffects, name)(source())
            self.assertGreaterEqual(len(rack.effects), 3)
            self.assertGreater(peak(rack.output, 8), 0.001, name)


if __name__ == "__main__":
    unittest.main()
