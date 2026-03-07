## SPEC Compliance Matrix

This document maps the Astra implementation to the normative clauses in `SPEC.md`. For each major section, it lists representative clauses, their primary implementation locations, and the tests that exercise them.

This matrix is intentionally high-level rather than line-by-line; multiple closely related SPEC rules may be covered by a single implementation entry and test.

---

### 1. Lexical Grammar

| SPEC clause | Implementation | Tests |
| --- | --- | --- |
| Keywords / operators / punctuation (`keyword`, `multi_op`, `single_op`) | `astra/lexer.py` (`KEYWORDS`, `MULTI_TOKENS`, `SINGLE_TOKENS`, `lex`) | `tests/test_lexer.py::test_lexes_keywords_and_symbols` (implicit via token checks), property fuzz in `tests/test_property_fuzz.py` |
| Integer literal forms (`int_lit`, `hex_int_lit`, `bin_int_lit`, separators) | `astra/lexer.py::_scan_digits_with_separators`, integer branches in `lex` | `tests/test_lexer.py::test_lexes_prefixed_and_separator_integer_literals`, `tests/test_lexer.py::test_invalid_separator_literals_emit_lex_error` |
| Dynamic integer type tokens (`int_type_tok`, widths 1..128) | `astra/int_types.py` (`INT_WIDTH_MIN/MAX`, `prefixed_int_width_error`, `parse_prefixed_int_type`); used from `lexer.lex` | `tests/test_lexer.py::test_lexes_dynamic_integer_type_tokens`, `tests/test_lexer.py::test_invalid_integer_width_tokens_emit_lex_error`, `tests/test_fixed_int_types.py::*` |
| String/char/boolean literals (`str_lit`, `char_lit`, `bool_lit`) | String/char branches in `lexer.lex`; `BOOL` tokens | `tests/test_lexer.py::test_lexes_literals_and_comments` (existing), parser coverage in `tests/test_parser.py` |
| Multiline string literals `str_multi_lit` | Tokenized as `STR_MULTI` in `lexer.lex`; parsed as `Literal` in `parser.parse_atom` | `tests/test_lexer.py::test_lexes_multiline_string_literal`, `tests/test_parser.py::test_parse_accepts_multiline_string_literal`, runtime behavior in `tests/test_golden_helpers.py::test_multiline_string_behaves_consistently_across_backends` |
| `@packed` attribute recognition | `lexer.SINGLE_TOKENS` includes `@`; attribute handling in `parser.Parser.parse_top_level` (`@packed` only valid on `struct`) | `tests/test_parser.py::test_parse_packed_struct_attribute`, `tests/test_build.py::test_build_native_supports_packed_struct_bitfield_ops`, `tests/test_build.py::test_build_native_supports_packed_struct_fields_above_64_bits`, `tests/test_build.py::test_build_llvm_supports_packed_struct_fields_above_64_bits` |

---

### 2. Expression Grammar & Coalesce

| SPEC clause | Implementation | Tests |
| --- | --- | --- |
| Expression precedence/associativity (`expr`, `coalesce_expr`, `logic_or_expr`, …) | Pratt-style precedence via `BIN_PREC` and `Parser.parse_expr` | `tests/test_parser.py::test_precedence_and_unary_and_chained_postfix`, property fuzz in `tests/test_property_fuzz.py` |
| Unary operators (including `await`, `&`, `&mut`, `*`) | `Parser.parse_unary`; AST nodes `Unary`, `AwaitExpr` in `astra/ast.py` | `tests/test_parser.py::test_parse_mutable_borrow_unary_expression`, async tests in `tests/test_build.py::test_build_native_supports_async_struct_and_defer_loop` |
| Layout/type intrinsics (`sizeof`, `alignof`, `size_of`, `align_of`, `bitSizeOf`, `maxVal`, `minVal`) | Parsing in `parser.parse_atom`; type checking in `semantic._infer` (`SizeOfTypeExpr`, `AlignOfTypeExpr`, `SizeOfValueExpr`, `AlignOfValueExpr`, `BitSizeOfTypeExpr`, `MaxValTypeExpr`, `MinValTypeExpr`); layout in `astra/layout.py` | `tests/test_parser.py::test_parse_bitwise_shift_cast_and_layout_queries`, `tests/test_parser.py::test_parse_bit_intrinsics_with_type_arguments`, `tests/test_build.py::test_build_native_supports_layout_queries`, `tests/test_semantic.py::test_layout_query_rejects_opaque_and_unsized_types` |
| Coalesce operator `a ?? b` typing (`a: Option<T>`, `b: T`, result `T`) | Semantic typing in `semantic._infer` (`Binary` branch `e.op == "??"`, `_is_option_type`, `_option_inner`); LLVM type inference in `llvm_codegen._expr_type` | `tests/test_semantic.py::test_coalesce_type_inference`, `tests/test_semantic.py::test_coalesce_requires_option_left_operand`, `tests/test_semantic.py::test_type_sugar_question_mark_desugars_to_option`, new runtime tests `tests/test_coalesce_runtime.py::*` |
| Coalesce short-circuiting & left-to-right eval | Py backend lowering in `codegen._expr` (lambda wrapper for `??`); LLVM lowering in `llvm_codegen._compile_expr` `e.op == "??"` branch with basic blocks and conditional branch | `tests/test_coalesce_runtime.py::test_coalesce_short_circuits_when_some`, `tests/test_coalesce_runtime.py::test_coalesce_evaluates_rhs_when_none`, `tests/test_evaluation_order_runtime.py::test_binary_ops_and_call_args_are_left_to_right` (covers general eval order) |
| Try-propagation postfix (`a!`) for `Option<T>` and `Result<T, E>` | Parser postfix support in `Parser.parse_postfix` (`TryExpr`), semantic checks in `semantic._infer` (`TryExpr` branch), backend lowering in `codegen._expr` + function wrapper (Option/Result) and `llvm_codegen._compile_expr` + `llvm_codegen._compile_call` (Option/Result) | `tests/test_parser.py::test_parse_try_postfix_operator`, `tests/test_semantic.py::test_try_operator_typechecks_for_option_in_option_returning_fn`, `tests/test_semantic.py::test_try_operator_typechecks_for_result_in_result_returning_fn`, `tests/test_semantic.py::test_try_operator_result_requires_result_return_type`, `tests/test_semantic.py::test_try_operator_result_requires_matching_error_type`, `tests/test_try_runtime.py::*` |

---

### 3. Statements & Control Flow

| SPEC clause | Implementation | Tests |
| --- | --- | --- |
| Statement forms (`block`, `binding_stmt`, `return`, loops, `if`, `match`, `defer`, `drop`, `comptime`) | `parser.parse_stmt`, `parse_block`, `parse_for`, `parse_match`; AST nodes in `astra/ast.py` (`LetStmt`, `ReturnStmt`, `IfStmt`, `WhileStmt`, `ForStmt`, `MatchStmt`, `DeferStmt`, `DropStmt`, `ComptimeStmt`) | `tests/test_parser.py::test_for_break_continue_import_struct_enum_mut_pub_assign`, `tests/test_parser.py::test_parse_defer_and_coalesce`, `tests/test_parser.py::test_parse_drop_stmt`, `tests/test_parser.py::test_parse_impl_fn_specializations`, control-flow heavy programs in `tests/test_full_programs.py` |
| Universal `for-in` loops (`for x in iterable`) over ranges/Vec/slices/Bytes | Parsed only as `for <ident> in <expr>` in `parser.parse_for`; type-checked in `semantic._check_stmt`; lowered to `while` + hygienic temporaries by `for_lowering.lower_for_loops` before optimization/codegen | `tests/test_parser.py::test_parse_range_for_builds_for_in_range_expr`, `tests/test_parser.py::test_parse_for_rejects_c_style_loop`, `tests/test_semantic.py::test_range_for_loop_typechecks`, `tests/test_semantic.py::test_vec_for_loop_typechecks`, `tests/test_semantic.py::test_slice_for_loop_typechecks`, `tests/test_semantic.py::test_bytes_for_loop_typechecks`, runtime in `tests/test_full_programs.py::test_full_program_for_in_ranges`, `tests/test_full_programs.py::test_full_program_for_in_vec_and_bytes` |
| Match wildcard arm (`_`) and coverage rules for Bool + enum variants | Wildcard parsing in `parser.parse_match` (`WildcardPattern`), semantic checks in `semantic._check_stmt` (wildcard-last, duplicate Bool/enum variant rejection, Bool + enum exhaustiveness), backend lowering in `codegen._stmt_py` and `llvm_codegen._compile_stmt` | `tests/test_parser.py::test_parse_match_accepts_wildcard_pattern`, `tests/test_semantic.py::test_match_wildcard_makes_bool_match_exhaustive`, `tests/test_semantic.py::test_match_wildcard_must_be_last`, `tests/test_semantic.py::test_match_duplicate_bool_pattern_is_rejected`, `tests/test_semantic.py::test_match_non_exhaustive_enum_is_rejected`, `tests/test_semantic.py::test_match_duplicate_enum_variant_is_rejected`, runtime in `tests/test_golden_helpers.py::test_range_for_and_match_wildcard_consistent_across_backends` |
| Mutable vs immutable binding semantics | Checked in `semantic._analyze_block` and helpers (`_require_mutable_binding`, immutable scopes); `LetStmt.is_mut` flag from parser | `tests/test_fixed_int_types.py::*` (assignment to immutable, immutable in `for` initializers), `tests/test_semantic.py::test_mutable_borrow_requires_mutable_binding` |
| `comptime` blocks | Frontend in `parser.parse_stmt` (`ComptimeStmt`), execution in `comptime.run_comptime` and `build.build` (`run_comptime(...)`) | `tests/test_full_programs.py::test_full_program_comptime_recursive_fold`, `tests/test_comptime.py::*` |

---

### 4. Module Resolution

| SPEC clause | Implementation | Tests |
| --- | --- | --- |
| Import forms (`import std.io;`, `import stdlib::io;`, `import "path";`, `as` aliases) | Parsing in `parser.parse_import`; resolution in `module_resolver.resolve_imports` and `build._build_fingerprint` (dependency tracking) | `tests/test_parser.py::test_import_supports_dotted_module_and_string_forms`, `tests/test_module_resolver.py::*`, `tests/test_build.py::test_build_cache_invalidates_when_imported_module_changes`, `tests/test_build.py::test_build_cache_invalidates_when_string_imported_module_changes` |
| Stdlib search order and package roots (`Astra.toml`) | `module_resolver.resolve_module` and helpers; stdlib path selection in `astra/stdlib/__init__.py` and `runtime.assets` | `tests/test_stdlib_modules.py::*`, packaging tests in `tests/test_packaging_integration.py` and `tests/test_packaged_assets.py` |

---

### 5. Type System & Unsized Types

| SPEC clause | Implementation | Tests |
| --- | --- | --- |
| Dynamic-width ints, aliases (`Int`, `iN/uN`, `isize/usize`) | `astra/int_types.py` (`parse_int_type_name`, `is_int_type_name`); used from semantic, layout, LLVM backend | `tests/test_fixed_int_types.py::*`, `tests/test_layout_dynamic_int.py::*`, `tests/test_build.py::test_build_native_supports_packed_struct_fields_above_64_bits`, `tests/test_build.py::test_build_llvm_supports_packed_struct_fields_above_64_bits` |
| Option sugar `T?` ↔ `Option<T>` and `none` rules | Type parsing in `parser.parse_type` (`?` loop), semantic checks in `semantic._validate_decl_type`, `_is_option_type`, `_option_inner`, `NONE_LIT_TYPE` | `tests/test_parser.py::test_parse_option_type_sugar`, `tests/test_semantic.py::test_coalesce_type_inference`, `tests/test_semantic.py::test_none_requires_option_context`, `tests/test_semantic.py::test_none_allowed_with_explicit_option_type`, `tests/test_semantic.py::test_option_type_accepts_plain_inner_value_as_some` |
| Unsized types (`str`, `[T]`) cannot be used by value | Unsized detection in `semantic._is_unsized_value_type`; enforcement via `_require_sized_value_type` for parameters and locals | `tests/test_semantic.py::test_unsized_slice_param_by_value_is_rejected`, `tests/test_semantic.py::test_unsized_str_local_by_value_is_rejected` (also exercised indirectly by `tests/test_evaluation_order_runtime.py` before fix) |
| Mixed int/float arithmetic requires explicit cast | `_is_int_type`, `_is_float_type`, `_require_strict_int_operands`, and diagnostics in `semantic._infer` for `Binary` | `tests/test_semantic.py::test_mixed_int_float_arithmetic_requires_explicit_cast`, `tests/test_semantic.py::test_cast_bool_to_int_is_allowed` |

---

### 6. Move/Borrow & Ownership

| SPEC clause | Implementation | Tests |
| --- | --- | --- |
| Copy vs move types (scalars & shared refs copyable; others move-only) | Ownership state tracked in `_OwnedState`, `_BorrowState`, `_MoveState` within `semantic.py`; helpers `_is_copy_type`, `_record_move`, `_record_use` | `tests/test_semantic.py::test_use_after_move_is_rejected_for_non_copy_values`, `tests/test_semantic.py::test_drop_consumes_non_copy_values`, `tests/test_semantic.py::test_copy_values_are_usable_after_assignment` |
| Shared vs mutable borrows; exclusivity rules | Borrow rules in `_borrow_value`, `_check_call_arg_borrows` and associated helpers | `tests/test_semantic.py::test_mutable_borrow_blocks_shared_borrow`, `tests/test_semantic.py::test_shared_borrow_blocks_mutation`, `tests/test_semantic.py::test_mutable_borrow_blocks_direct_use_of_owner`, `tests/test_semantic.py::test_multiple_shared_borrows_are_allowed`, `tests/test_semantic.py::test_mutable_borrow_requires_mutable_binding` |
| Returned reference must tie to input reference origin | Lifetime checks in `_validate_ref_return` and `_check_fn_returns` in `semantic.py` | `tests/test_semantic.py::test_ref_return_without_ref_param_is_rejected`, `tests/test_semantic.py::test_ref_return_must_tie_to_ref_param`, `tests/test_semantic.py::test_ref_return_alias_of_ref_param_is_allowed` |
| Owned-state checks (use-after-free/move, leaks) carry real spans | Owned-state diagnostics wired through `_diag` using filename/line/col; no remaining `SEM <input>:1:1` in code | `tests/test_semantic.py::test_owned_internal_use_after_free_reports_exact_location`, `tests/test_semantic.py::test_owned_internal_use_after_move_reports_exact_location`, `tests/test_semantic.py::test_owned_internal_reassignment_leak_reports_exact_location` |

---

### 7. Evaluation Order Guarantees

| SPEC clause | Implementation | Tests |
| --- | --- | --- |
| Strict left-to-right evaluation of expressions and call arguments | Parser builds left-associated `Binary` trees; Py backend expression printer `_expr` always renders left operand first; LLVM backend `_compile_expr` evaluates `e.left` before `e.right` and respects that order in branches | `tests/test_evaluation_order_runtime.py::test_binary_ops_and_call_args_are_left_to_right` |
| Short-circuiting of `&&`, `||`, `??` | Boolean ops lowered with explicit control flow in `llvm_codegen._compile_expr` and short-circuit helpers; coalesce lowering as described above; Py backend uses Python's own short-circuit semantics for `and`/`or` and a lambda-based pattern for `??` | Existing optimizer and backend tests (`tests/test_optimizer_edges.py`, `tests/test_build.py::test_build_native_shift_out_of_range_traps`) plus new `tests/test_coalesce_runtime.py::*` and `tests/test_evaluation_order_runtime.py::*` |
| `defer` executes LIFO at function exit | Frontend `DeferStmt`, runtime lowering in both backends via `comptime`/codegen defers | `tests/test_build.py::test_build_native_supports_async_struct_and_defer_loop` (checks two `defer print("bye")` calls execute in correct order) |

---

### 8. Backend Boundaries (`py` vs `llvm/native`, freestanding)

| SPEC clause | Implementation | Tests |
| --- | --- | --- |
| Phase prefixes (`LEX`, `PARSE`, `SEM`, `CODEGEN`) in diagnostics | `_diag` helpers in `parser`, `semantic`, and codegen modules; backend failures formatted as `CODEGEN ...` in `astra/codegen.py`, `astra/llvm_codegen.py`, `astra/build.py` | Dozens of tests match full diagnostic strings: e.g. `tests/test_semantic.py::test_owned_internal_use_after_free_reports_exact_location`, `tests/test_semantic.py::test_owned_internal_use_after_move_reports_exact_location`, new `tests/test_build.py::test_native_missing_clang_reports_codegen_error` |
| Hosted vs freestanding behavior; rejection of runtime builtins under `--freestanding` | Semantic freestanding checks in `semantic.analyze` (rejecting hosted builtins like `print` when `freestanding=True`); runtime-free constraints enforced on LLVM IR via `_require_runtime_free_freestanding` in `build._require_runtime_free_freestanding` | `tests/test_build.py::test_build_freestanding_rejects_runtime_builtins`, `tests/test_build.py::test_build_freestanding_rejects_external_host_symbols`, `tests/test_build.py::test_build_freestanding_supports_vec_builtins_without_runtime_symbols`, `tests/test_build.py::test_build_freestanding_supports_array_literals_and_struct_constructors` |
| `native --freestanding` requires `fn _start()` | Checked in `build.build` before semantic analysis (`has_start` over `FnDecl` items) | `tests/test_build.py::test_build_native_freestanding_requires_start_symbol` |
| Freestanding vector builtins avoid `astra_*` runtime symbols | Lowered via freestanding-specific helpers in `llvm_codegen` and checked by `_require_runtime_free_freestanding` | `tests/test_build.py::test_build_freestanding_supports_vec_builtins_without_runtime_symbols`, `tests/test_build.py::test_build_freestanding_supports_array_literals_and_struct_constructors` |
| Backend-only limitations reported as CODEGEN, not SEM | Backend errors raised via `CodegenError` / `RuntimeError` with `CODEGEN` prefix in `build._build_native_llvm`, `_strict_validate_program`, `_require_runtime_free_freestanding` | New `tests/test_build.py::test_native_missing_clang_reports_codegen_error` plus existing freestanding/strict-mode tests that assert CODEGEN messages |

---

### 9. Diagnostics & Spans

| SPEC clause | Implementation | Tests |
| --- | --- | --- |
| Every AST node carries a span; diagnostics use node spans consistently | AST dataclasses in `astra/ast.py` all include `pos/line/col`; helpers `_diag` in `parser`, `semantic`, `codegen`, and `llvm_codegen` always use node or filename + source coordinates | Span-sensitive tests in `tests/test_semantic.py` (`test_owned_internal_*`), parser multi-error tests `tests/test_parser.py::test_multi_error_recovery_collects_multiple`, and LSP diagnostics checks in `tests/test_tooling_inprocess.py::test_lsp_helpers_and_main_dispatch` |
| Structured diagnostics for `astra check --json` with stable codes (`E*/W*`) | CLI handling in `astra/check.py` and `astra/cli.py`; LSP and CLI share the same check pipeline | `tests/test_check.py::*` (JSON and span structure), `tests/test_tooling_inprocess.py::test_lsp_helpers_and_main_dispatch` (parses diagnostics and asserts stable `E0100` code) |
| No remaining hardcoded `SEM <input>:1:1` in semantic/internal checks | All semantic errors call `_diag(filename, line, col, ...)`; owned-state helpers receive filename/line/col and propagate them into diagnostics | Verified by a repo-wide search (no `SEM <input>` in code), plus exact-span tests in `tests/test_semantic.py::test_owned_internal_use_after_free_reports_exact_location`, `tests/test_semantic.py::test_owned_internal_use_after_move_reports_exact_location`, `tests/test_semantic.py::test_owned_internal_reassignment_leak_reports_exact_location` |

---

### 10. Summary of Newly Added SPEC-Covering Tests

- **Multiline strings**: lexer/parser/backend round-trip via `tests/test_lexer.py::test_lexes_multiline_string_literal`, `tests/test_parser.py::test_parse_accepts_multiline_string_literal`, `tests/test_golden_helpers.py::test_multiline_string_behaves_consistently_across_backends`.
- **Coalesce semantics**: runtime short-circuiting and typing exercised in `tests/test_coalesce_runtime.py::*`.
- **Evaluation order**: explicit left-to-right guarantees validated in `tests/test_evaluation_order_runtime.py::test_binary_ops_and_call_args_are_left_to_right`.
- **Backend boundary / CODEGEN classification**: missing-clang scenario asserted as `CODEGEN` in `tests/test_build.py::test_native_missing_clang_reports_codegen_error`.
- **Range loops + wildcard match**: parser/semantic/codegen coverage added in `tests/test_parser.py::*range*`, `tests/test_semantic.py::*wildcard*`, and cross-backend runtime `tests/test_golden_helpers.py::test_range_for_and_match_wildcard_consistent_across_backends`.
