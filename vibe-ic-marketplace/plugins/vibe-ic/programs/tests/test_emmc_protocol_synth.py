"""eMMC (JEDEC JESD84-B51) protocol-synth detector + MUTEX regression tests.

Pins the eMMC detector's CONTENT-ONLY, general-not-keyword behaviour and the
hard MUTEX vs the derived-sibling protocols it shares vocabulary with:
SD/MMC (CMD/DAT command bus), UFS (embedded managed-NAND, RPMB/CMDQ/eMMC
mention but serial M-PHY/UniPro), and ONFI (raw-NAND, 8-bit data bus + data
strobe). The eMMC detector must fire ONLY on a genuine eMMC parallel-command-bus
doc carrying an eMMC-EXCLUSIVE structural anchor (EXT_CSD / RST_n /
PARTITION_CONFIG / Boot Area Partition / Embedded MultiMediaCard / JESD84).
"""
from emmc_protocol_synth import is_emmc


_EMMC_DOC = """
Embedded MultiMediaCard (eMMC) Electrical Standard (5.1), JESD84-B51.
Bus: CLK, bidirectional CMD (48-bit token, CRC7), DAT[7:0] 8-bit data bus,
Data Strobe (DS) for HS400, hardware reset RST_n. Registers OCR/CID/CSD and a
512-byte Extended CSD (EXT_CSD). PARTITION_CONFIG selects Boot Area Partition 1,
Boot Area Partition 2, the Replay Protected Memory Block (RPMB) and General
Purpose Partitions. Speed modes HS200 (200 MB/s) and HS400 (400 MB/s DDR with
Data Strobe). Managed-NAND features: HPI, Background Operations (BKOPS), Cache,
Sanitize/TRIM/Discard, Field Firmware Update (FFU), Command Queuing (CMDQ).
"""

# A removable SD card doc — SD-primary names + ACMD41, and NO eMMC-exclusive
# anchor token anywhere (a real SD doc does not name EXT_CSD/RST_n/etc.).
_SD_DOC = """
SD Memory Card / SD Card, Secure Digital. Init uses ACMD41 with CMD line and
DAT0..DAT3 (4-bit). Card detect, write-protect switch, card insertion/removal.
SDIO function. CID/CSD/OCR registers, 4-bit data bus.
"""

# A UFS doc — embedded managed-NAND that shares RPMB/CMDQ and cites eMMC, but is
# a serial M-PHY / UniPro / SCSI stack carrying NO eMMC-exclusive anchor token.
_UFS_DOC = """
Universal Flash Storage (UFS). Serial MIPI M-PHY + UniPro link, SCSI command
set, UTP/UTRD. Embedded managed NAND, successor to eMMC. Supports RPMB,
boot partition and Command Queuing. HS-GEAR speeds over the serial link.
"""

# An ONFI raw-NAND doc — 8-bit data bus + data strobe but NO eMMC-exclusive
# anchor token (no EXT_CSD / RST_n / PARTITION_CONFIG / Boot Area Partition).
_ONFI_DOC = """
Open NAND Flash Interface (ONFI). Asynchronous/synchronous raw NAND, 8-bit data
bus, Data Strobe (DQS), read enable / write enable / chip enable / ALE / CLE
control. RPMB optional. Page program and block erase.
"""


def test_fires_on_emmc_doc():
    assert is_emmc(_EMMC_DOC) is True


def test_empty_and_none_safe():
    assert is_emmc("") is False
    assert is_emmc(None) is False  # type: ignore[arg-type]


def test_mutex_defers_on_sd_card():
    assert is_emmc(_SD_DOC) is False


def test_mutex_defers_on_ufs():
    assert is_emmc(_UFS_DOC) is False


def test_mutex_defers_on_onfi():
    assert is_emmc(_ONFI_DOC) is False


def test_requires_emmc_exclusive_anchor_not_shared_vocab_alone():
    # 8-bit DAT bus + RPMB + CMDQ WITHOUT an eMMC-exclusive anchor (no EXT_CSD,
    # no RST_n, no PARTITION_CONFIG, no Boot Area Partition, no embedded-MMC
    # name, no JESD84) must NOT fire — those tokens are enumerated by foreign
    # managed-NAND docs too.
    shared_only = (
        "8-bit data bus DAT[7:0]. RPMB Replay Protected Memory Block. "
        "Command Queuing CMDQ. HS400. Background Operations BKOPS."
    )
    assert is_emmc(shared_only) is False


def test_content_only_no_filename_read():
    # The detector takes a single string blob; it has no access to filenames.
    # A blob naming the eMMC structure fires regardless of any (absent) path.
    assert is_emmc(_EMMC_DOC) is True
    # The literal benchmark folder name alone ("emmc") must NOT fire.
    assert is_emmc("emmc") is False
