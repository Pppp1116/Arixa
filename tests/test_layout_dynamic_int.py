from astra.layout import layout_of_type


def test_layout_for_sub_byte_and_non_standard_int_widths():
    u3 = layout_of_type("u3", {}, mode="query")
    u9 = layout_of_type("u9", {}, mode="query")
    i127 = layout_of_type("i127", {}, mode="query")
    assert (u3.size, u3.bits, u3.signed) == (1, 3, False)
    assert (u9.size, u9.bits, u9.signed) == (2, 9, False)
    assert (i127.size, i127.bits, i127.signed) == (16, 127, True)
