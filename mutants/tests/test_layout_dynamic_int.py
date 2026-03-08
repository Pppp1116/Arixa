from astra.layout import layout_of_struct, layout_of_type
from astra.parser import parse


def test_layout_for_sub_byte_and_non_standard_int_widths():
    u3 = layout_of_type("u3", {}, mode="query")
    u9 = layout_of_type("u9", {}, mode="query")
    i127 = layout_of_type("i127", {}, mode="query")
    assert (u3.size, u3.bits, u3.signed) == (1, 3, False)
    assert (u9.size, u9.bits, u9.signed) == (2, 9, False)
    assert (i127.size, i127.bits, i127.signed) == (16, 127, True)


def test_layout_for_packed_struct_tracks_bit_offsets():
    prog = parse(
        """
@packed struct Header {
  version: u4,
  flags: u3,
  enabled: u1,
}
"""
    )
    structs = {item.name: item for item in prog.items}
    lay = layout_of_struct("Header", structs, mode="query")
    assert lay.packed
    assert lay.bits == 8
    assert lay.size == 1
    assert lay.align == 1
    assert lay.field_bit_offsets["version"] == 0
    assert lay.field_bit_offsets["flags"] == 4
    assert lay.field_bit_offsets["enabled"] == 7
    assert lay.field_bits["enabled"] == 1
