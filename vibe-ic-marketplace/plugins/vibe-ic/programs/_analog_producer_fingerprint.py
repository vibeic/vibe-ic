"""Source identities shared by analog producers and their reuse consumer."""
import hashlib
from pathlib import Path


_DEPENDENCIES = {
    "analog_a2_topology_emit.py": (
        "analog_ciff.py", "analog_ota1_options.py",
        "_analog_producer_fingerprint.py"),
}


def producer_fingerprint(program: Path) -> str:
    """Hash the producer and the source dependencies that shape its output."""
    sources = (program.name, *_DEPENDENCIES.get(program.name, ()))
    try:
        return hashlib.sha256(b"".join(
            (program.parent / name).read_bytes() for name in sources
        )).hexdigest()[:16]
    except OSError:
        return ""
