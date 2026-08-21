"""Dedicated SENT (SAE J2716) detector edge-case guard.

The universal ``test_protocol_detector_no_misfire`` auto-covers ``is_sent``
firing only on its own benchmark. This file adds the SENT-SPECIFIC edge cases
called out as HARD constraints when the class was added:

  * is_sent MUST NOT fire on the bare English word "sent" in prose
    (e.g. "the data was sent to the host") — the detector keys on SENT-
    structural tokens (SAE J2716 / single edge nibble + nibble + tick +
    56-tick calibration pulse + nibble-timing rule), never the word "sent".
  * is_sent MUST NOT fire on hand-crafted LIN / DALI / generic-PWM blobs
    (the single-wire / pulse siblings), per the MUTEX.
  * is_sent fires on the canonical SENT structural signature.
  * content-only: no filename / folder reads.
"""
from sent_protocol_synth import is_sent


def test_empty_and_none_safe():
    assert is_sent("") is False
    assert is_sent(None) is False  # type: ignore[arg-type]


def test_does_not_fire_on_the_word_sent_in_prose():
    assert is_sent("The data was sent to the host.") is False
    assert is_sent("The host then sent an acknowledgement back to the sensor "
                   "and the message was sent again on timeout.") is False
    # even with unrelated "tick" and "crc" words present, no SENT structure:
    assert is_sent("A packet was sent every tick and a CRC was appended.") \
        is False


def test_fires_on_canonical_sent_structure():
    blob = (
        "Single Edge Nibble Transmission (SENT), SAE J2716. Data is conveyed "
        "on a single signal wire by the time between successive falling edges, "
        "measured in ticks (unit time, nominal 3 us). Each nibble is a pulse "
        "of 12 + value ticks (value 0-15). Every frame begins with a 56-tick "
        "synchronization/calibration pulse, then a status nibble, 1-6 data "
        "nibbles, and a 4-bit CRC (CRC-4) nibble."
    )
    assert is_sent(blob) is True


def test_fires_via_nibble_timing_rule_without_explicit_value_string():
    blob = (
        "SAE J2716 single edge nibble transmission. The nibble pulse period is "
        "measured falling edge to falling edge in ticks (unit time). A 56-tick "
        "calibration pulse precedes the status nibble, the data nibbles, and "
        "the CRC nibble (4-bit)."
    )
    assert is_sent(blob) is True


def test_does_not_fire_on_lin():
    lin = (
        "LIN bus 2.2A (Local Interconnect Network). A UART-based serial bus "
        "with a master node and slave nodes following a master schedule. Each "
        "frame has a break field, a sync field, and a protected identifier "
        "(PID). Bytes are framed with start and stop bits."
    )
    assert is_sent(lin) is False


def test_does_not_fire_on_dali():
    dali = (
        "DALI (Digital Addressable Lighting Interface). A Manchester-coded "
        "bidirectional lighting-control bus. Forward and backward frames carry "
        "a nibble of address and a nibble of command over the lighting bus."
    )
    # has 'nibble' but Manchester+lighting and no SAE-J2716 / tick / 56-tick.
    assert is_sent(dali) is False


def test_does_not_fire_on_generic_pwm():
    pwm = (
        "The sensor reports its value as a PWM output: a fixed-period square "
        "wave whose duty cycle is proportional to the measured pressure. There "
        "are no nibbles and no message frame."
    )
    assert is_sent(pwm) is False


def test_does_not_fire_on_uart():
    uart = (
        "PC16550D UART. Asynchronous serial with a start bit, eight data bits, "
        "an optional parity bit, and a stop bit. SIN and SOUT lines. Baud rate "
        "set by a divisor."
    )
    assert is_sent(uart) is False


def test_apply_is_noop_when_flag_false(tmp_path):
    # apply_sent_synth must do nothing (and not raise) when the flag is False.
    from sent_protocol_synth import apply_sent_synth
    apply_sent_synth(tmp_path, False, "X")  # no files, no error
    assert not list(tmp_path.glob("*.json"))
