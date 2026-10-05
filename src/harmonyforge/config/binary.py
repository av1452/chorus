"""The shared outer container of a Harmony config binary.

This is a different, separately-sourced layer of knowledge from the rest of
harmonyforge: everything elsewhere in this package (the USB protocol, the
device/architecture tables) comes from libconcord, which treats the config
region as an opaque blob it only ever moves, never interprets. This module
instead parses the *inside* of that blob.

That inside has a real structure, reverse-engineered by the
`harmony-decompiler <https://github.com/trelowney/harmony-decompiler>`_
project (GPLv3): a small binary header, then a table of absolute flash
addresses pointing at 18 (plus a null terminator) contiguous sections. The
header shape -- the cookie/magic, an end-of-config address, a mystery
constant, the pointer table, and the markers bracketing it -- has been
confirmed identical across architectures 8, 9, 12 and 14, with only the
four-letter magic strings differing per architecture. See NOTICE.md.

**What this module does NOT do**: decode what is inside each section. That
is unmapped for architecture 14 (the subject of this port) -- nobody has
published a device/activity/button-table decode for it yet. This module
gets you to the start of each section and its byte range; the content past
that point is exactly as opaque to harmonyforge as it was before. Nothing
here writes to a remote.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import HarmonyForgeError


class BinaryFormatError(HarmonyForgeError):
    """A config blob did not match the expected container shape.

    Raised instead of silently guessing, because a config is a compiled
    image full of absolute pointers -- see ``docs/binary-config-format.md``
    for why treating a mismatched assumption as "close enough" produces
    garbage rather than a clear failure.
    """


@dataclass(frozen=True)
class ContainerSignature:
    """The four architecture-specific constants that bracket the header.

    ``slot_count`` includes the trailing null terminator slot, so a real
    config has ``slot_count - 1`` populated sections.
    """

    architecture: int
    cookie: bytes
    header_end_marker: bytes
    blob_end_marker: bytes
    slot_count: int


#: Confirmed, per-architecture container constants.
#:
#: Established by @dannybloe over a thirteen-sample corpus
#: (harmony-decompiler issue #66 and FORMAT.md §5), and independently
#: re-confirmed here against a real Harmony 665 (architecture 14) backup:
#: the GSPM cookie decodes to exactly the same 0x4D505347 value libconcord's
#: own (separately-sourced) architecture table already carried for arch 14,
#: and the config_base recovered from this header's own fields matches
#: libconcord's value exactly. Architectures 8 and 9 are listed for
#: completeness but have not been checked against real data by this port.
CONTAINER_SIGNATURES: dict[int, ContainerSignature] = {
    8: ContainerSignature(8, b"TPTP", b"WLWL", b"DKDK", 20),
    9: ContainerSignature(9, b"AHCM", b"CMAH", b"MCHA", 19),
    12: ContainerSignature(12, b"GSPM", b"LWJL", b"PTYY", 21),
    14: ContainerSignature(14, b"GSPM", b"LWJL", b"PTYY", 19),
}

#: Byte offset of the first section pointer, constant across architectures.
POINTER_TABLE_OFFSET = 0x0C

#: Bit that libconcord's own architecture table sets on some config_base
#: values (e.g. architecture 9's documented 0x820000) but which the header's
#: own end-of-config address does not include. harmony-decompiler's finding:
#: "bit 23 looks like a flag rather than an address bit." Masked off when
#: cross-checking a computed base against the known one.
_BASE_FLAG_BIT = 1 << 23


@dataclass(frozen=True)
class Section:
    """One entry in the section pointer table.

    ``length`` is the gap to the next section's address, which is how
    harmony-decompiler establishes sections are contiguous with no gaps
    between them. The last real section's length instead runs to the start
    of the header-end-marker's mirror at the tail of the blob, since there
    is no next pointer to diff against.
    """

    index: int
    address: int
    file_offset: int
    length: int | None

    @property
    def is_present(self) -> bool:
        """False for a null slot -- that subsystem is absent from this config.

        Confirmed on real data: architecture 8 configs carry a null in the
        middle of their table, not only at the end, and naively reading
        until the first zero silently truncates the table. Callers must
        check this rather than assume every non-terminator slot is real.
        """
        return self.address != 0


@dataclass(frozen=True)
class ContainerHeader:
    """A parsed config container: header fields plus the section table."""

    architecture: int
    cookie: bytes
    end_address: int
    unknown_field: int
    config_base: int
    sections: tuple[Section, ...]

    def section(self, index: int) -> Section:
        """Look up a slot by index, whether present or not.

        Raises only if ``index`` is not a slot this architecture has at
        all. A present-but-null slot is a legitimate answer, not a
        failure -- check the result's ``.is_present`` yourself. Use
        :meth:`read_section` instead if you want "give me the bytes, and
        fail clearly if that is not possible" in one call.
        """
        for candidate in self.sections:
            if candidate.index == index:
                return candidate
        raise BinaryFormatError(
            f"no section {index}; this architecture has "
            f"{len(self.sections)} slots (0-{len(self.sections) - 1})"
        )

    def read_section(self, blob: bytes, index: int) -> bytes:
        """Return the raw bytes of section ``index``.

        Raises if the section is absent (a null slot -- that subsystem
        is simply not in this config) or if its length could not be
        computed (true for the last real section, which has no next
        pointer to diff against -- slice ``blob`` from its ``file_offset``
        yourself with whatever end you intend).
        """
        section = self.section(index)
        if not section.is_present:
            raise BinaryFormatError(
                f"section {index} is null in this config -- that "
                "subsystem is simply not present, there is nothing to read"
            )
        if section.length is None:
            raise BinaryFormatError(
                f"section {index} has no computed length (it is likely the "
                "last real section); slice the blob from its file_offset "
                "yourself with whatever end you intend"
            )
        start = section.file_offset
        return blob[start : start + section.length]


def _read_u32(blob: bytes, offset: int) -> int:
    if offset + 4 > len(blob):
        raise BinaryFormatError(
            f"blob is only {len(blob)} bytes, too short to read a u32 at "
            f"offset 0x{offset:X}"
        )
    return int.from_bytes(blob[offset : offset + 4], "little")


def parse_container(blob: bytes, architecture: int, config_base: int) -> ContainerHeader:
    """Parse the outer container of a config blob.

    ``config_base`` should come from
    :func:`harmonyforge.devicedb.architecture` -- it is used only to cross-
    check against the base this header's own fields imply, and to convert
    the absolute addresses in the pointer table into file offsets.

    Raises :class:`BinaryFormatError` on anything that does not match the
    documented shape, rather than guessing: a config is a compiled image
    full of absolute pointers, so a wrong assumption here does not fail
    loudly later -- it produces a plausible-looking wrong answer.
    """
    try:
        signature = CONTAINER_SIGNATURES[architecture]
    except KeyError:
        known = ", ".join(str(a) for a in sorted(CONTAINER_SIGNATURES))
        raise BinaryFormatError(
            f"no known container signature for architecture {architecture}. "
            f"Known: {known}. This does not mean architecture {architecture} "
            "uses a different format -- it means nobody has confirmed this "
            "one against it yet."
        ) from None

    if blob[:4] != signature.cookie:
        raise BinaryFormatError(
            f"expected cookie {signature.cookie!r} for architecture "
            f"{architecture} at offset 0, found {blob[:4]!r}. Either this "
            "is not an architecture-{architecture} config, or the blob does "
            "not start at the config region (strip any XML .EZHex header "
            "first -- this function wants the raw binary blob only)."
        )

    end_address = _read_u32(blob, 4)
    unknown_field = _read_u32(blob, 8)

    slots = []
    for i in range(signature.slot_count):
        offset = POINTER_TABLE_OFFSET + 4 * i
        slots.append(_read_u32(blob, offset))

    if slots[-1] != 0:
        raise BinaryFormatError(
            f"expected the last of {signature.slot_count} pointer slots to "
            f"be a null terminator, found 0x{slots[-1]:08X}. The slot count "
            "for this architecture may be wrong, or this is not where the "
            "table actually ends."
        )

    marker_offset = POINTER_TABLE_OFFSET + 4 * signature.slot_count
    padding = blob[marker_offset : marker_offset + 3]
    if padding != b"\x00\x00\x00":
        raise BinaryFormatError(
            f"expected 3 zero padding bytes before the header-end marker "
            f"at offset 0x{marker_offset:X}, found {padding!r}"
        )

    marker_start = marker_offset + 3
    found_marker = blob[marker_start : marker_start + 4]
    if found_marker != signature.header_end_marker:
        raise BinaryFormatError(
            f"expected header-end marker {signature.header_end_marker!r} at "
            f"offset 0x{marker_start:X}, found {found_marker!r}"
        )

    if blob[-4:] != signature.blob_end_marker:
        raise BinaryFormatError(
            f"expected the blob to end with {signature.blob_end_marker!r}, "
            f"found {blob[-4:]!r}. The blob may be truncated."
        )

    computed_base = end_address - len(blob) + 4
    if computed_base != config_base:
        # The header's own arithmetic (computed_base) is derived purely from
        # this blob's bytes. The mismatch harmony-decompiler actually found
        # was on the *other* side: concordance's documented config_base for
        # architecture 9 (0x820000) carries an extra bit the header itself
        # does not. So it is the caller-supplied value that may need
        # masking, not the one computed here.
        masked_supplied = config_base & ~_BASE_FLAG_BIT
        if masked_supplied != computed_base:
            raise BinaryFormatError(
                f"config_base mismatch: this header implies 0x{computed_base:06X}, "
                f"but 0x{config_base:06X} was supplied (0x{masked_supplied:06X} "
                "with the known flag bit masked, which also does not match). "
                "Either the wrong architecture/config_base was passed, or the "
                "blob is not a whole, untruncated config region."
            )

    sections: list[Section] = []
    present = [(i, addr) for i, addr in enumerate(slots) if addr != 0]
    for position, (index, address) in enumerate(present):
        file_offset = address - config_base
        if position + 1 < len(present):
            next_address = present[position + 1][1]
            length: int | None = next_address - address
        else:
            length = None  # last real section; no next pointer to diff against
        sections.append(Section(index, address, file_offset, length))
    for index, address in enumerate(slots):
        if address == 0:
            sections.append(Section(index, 0, 0, None))
    sections.sort(key=lambda s: s.index)

    return ContainerHeader(
        architecture=architecture,
        cookie=signature.cookie,
        end_address=end_address,
        unknown_field=unknown_field,
        config_base=config_base,
        sections=tuple(sections),
    )
