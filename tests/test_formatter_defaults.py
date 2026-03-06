from pathlib import Path

from astra.formatter import FormatConfig, fmt, resolve_format_config


def test_formatter_multiline_blocks_and_top_level_spacing_default_indent():
    src = "fn a() Int{ return 1; }\nfn b() Int{ return 2; }\n"
    out = fmt(src)
    assert out == (
        "fn a() Int {\n"
        "    return 1;\n"
        "}\n"
        "\n"
        "fn b() Int {\n"
        "    return 2;\n"
        "}\n"
    )


def test_formatter_indent_width_from_astfmt_toml(tmp_path: Path):
    cfg_file = tmp_path / "astfmt.toml"
    cfg_file.write_text("indent_width = 2\n")
    src_file = tmp_path / "a.astra"
    src_file.write_text("fn main() Int{ return 1; }\n")
    cfg = resolve_format_config(src_file)
    out = fmt(src_file.read_text(), config=cfg)
    assert cfg.indent_width == 2
    assert "\n  return 1;\n" in out


def test_formatter_indent_width_from_astra_manifest(tmp_path: Path):
    manifest = tmp_path / "Astra.toml"
    manifest.write_text("[format]\nindent_width = 8\n")
    src_file = tmp_path / "a.astra"
    src_file.write_text("fn main() Int{ return 1; }\n")
    cfg = resolve_format_config(src_file)
    out = fmt(src_file.read_text(), config=cfg)
    assert cfg.indent_width == 8
    assert "\n        return 1;\n" in out


def test_formatter_wraps_long_function_signature_near_line_width():
    src = "fn heavy(alpha Int, beta Int, gamma Int, delta Int, epsilon Int, zeta Int) Int{ return 0; }\n"
    out = fmt(src, config=FormatConfig(indent_width=4, line_width=60))
    assert "fn heavy(" in out
    assert "\n    alpha Int,\n" in out
    assert ") Int {" in out
