DO NOT CHANGE THE FILE

Current design summary
Syntax style (actual parser): bindings are mut name[: Type] = expr; or name[: Type] = expr; (dual declaration/reassign), with explicit reassignment via set; function declarations are fn name(params) Ret { ... } (no -> in fn signatures).
Evidence: parser.py, lexer.py, formatter.py

Keyword model: includes trait, where, set, is; excludes let, fixed, impl in main compiler.
Evidence: lexer.py, test_lexer.py

Ownership/mutability model: move-by-default + borrow/move/owned-state checks; copy-by-default for scalar numerics, Bool, shared refs.
Evidence: semantic.py

Type/function style: parametric overloads, where trait bounds, trait declarations, unsafe/async/gpu function flags; postfix try-propagation is !.
Evidence: parser.py, ast.py, semantic.py

Builtins organization: centrally declared in BUILTIN_SIGS, with semantic freestanding/GPU gating, stdlib wrappers, and backend-specific lowering.
Evidence: semantic.py, codegen.py, llvm_codegen.py

Stdlib organization: main stdlib is duplicated as stdlib/ and astra/stdlib/ (in sync except README), with hosted/freestanding split by API.
Evidence: stdlib/, astra/stdlib/

Compiler pipeline: lex/parse → comptime → semantic (including recursive import loading) → for-lowering/optimizer → python or LLVM/native backend.
Evidence: build.py

Inconsistency report
#	Feature	Classification	Files involved	Why inconsistent	What code suggests	What docs/status suggest	Confidence	Safe to fix later
1	let / fixed bindings	migrated	lexer.py, parser.py, SPEC.md, TOUR.md, SPEC_COMPLIANCE.md, DIAGNOSTICS.md	Main parser does not parse let/fixed; docs now aligned	Current surface is mut name = ... / name = ... / set ...	Docs updated to current mut-based syntax	high	completed
2	-> in fn signatures	completed	parser.py, check.py, lsp.py, astra.code-snippets	Parser explicitly errors on -> in declarations; tooling suggests it	Return type must be after ) without arrow	Snippets/diagnostic suggestion still show fn ... -> ...	high	completed
3	impl keyword	likely obsolete	lexer.py, test_lexer.py, SPEC.md, editors/vscode/server/astra/parser.py	Main compiler removed impl; spec/editor fork still use it	Specialization is overload-based without impl keyword	Spec/editor server still model impl surface	high	yes
4	Try propagation operator (! vs ?)	partially migrated	parser.py, semantic.py, codegen.py, FEATURE_STATUS.md, SPEC_COMPLIANCE.md	Parser/semantic use postfix !, but docs and one runtime error string still mention ?	Current syntax is expr!	Status/spec-compliance still contain ? references	high	yes
5	Root spec vs active implementation	conflicting	SPEC.md, language-spec.md, parser.py	Two “spec” tracks disagree on keywords/grammar	Active code aligns much more with docs/language-spec.md	SPEC.md still encodes old model (let/fixed/impl, etc.)	high	yes
6	Trait/is/attrs/gpu fn coverage in formal docs	undocumented but implemented	parser.py, semantic.py, language-spec.md	Parser supports trait, where, is, @derive, @link, gpu fn; formal grammar coverage is incomplete	These are active language features	Formal language doc grammar under-specifies them	high	yes
7	Nullable union model vs Option<T> model	unclear / needs human decision	semantic.py, language-spec.md, reference-manual.md, core.astra	Compiler special-cases both models; they are not fully interchangeable (Int? vs Option<Int>)	Both tracks are live, with special-case semantics	Docs mostly present union-first story (`T? = T	none`)	high
8	std.core Option/Result generic declaration shape	conflicting	core.astra, docs/stdlib/core.md, parser.py, semantic.py	Docs claim Option<T>/Result<T,E> variants; source declares enums without <...> generics	Constructor typing expects explicit generics; current declarations are inconsistent	Stdlib docs describe fully generic enum variants	high	likely (but verify downstream)
9	panic builtin backend parity	partially migrated	semantic.py, llvm_codegen.py, codegen.py	panic is declared/typed and lowered in LLVM/native but not implemented in generated Python helpers	LLVM/native has runtime path; Python emits unresolved panic(...)	Docs imply language panic behavior broadly	high	yes
10	Main LSP/check syntax knowledge	partially migrated	lsp.py, check.py, parser.py	Completion/snippets/formatting metadata still encode old syntax	Parser is newer than LSP/check UX layers	Tooling docs imply compiler-aligned diagnostics/snippets	high	yes
11	VS Code bundled compiler/LSP fork drift	duplicate	editors/vscode/server/astra/, run_lsp.py, run_cli.py, package.json, astra/	Bundled fork preserves old parser/semantic/docs assumptions while main compiler evolved	Two compiler trees with divergent language behavior	Extension defaults to bundled mode, so stale behavior is user-facing	high	medium
12	Bundled VS Code stdlib drift/missing modules	dead/orphaned path	astra/stdlib/, editors/vscode/server/astra/stdlib/, run_lsp.py	Bundled stdlib misses thread/sync/channel and differs across many modules	Main compiler stdlib has newer module set	Feature/docs describe these modules as present	high	yes
13	Import-symbol loading status	documented but not implemented	semantic.py, build.py, modules.md	Docs say full symbol loading is limited; code recursively loads imported declarations/items	Import loading is materially implemented	Docs understate current behavior	high	yes
14	Self-hosting status messaging	conflicting	selfhost/compiler.astra, cli.py, reference-manual.md, FEATURE_STATUS.md, editors/vscode/server/astra/cli.py	Main code says staged pipeline exists but gated; docs and bundled CLI still say pure placeholder/file-copier	Prototype exists, not end-to-end	Docs disagree on whether any real pipeline exists	high	yes
15	README quick example validity	documented but not implemented	README.md, examples/hello_world.astra, parser.py	README code omits semicolons and is not parser-valid	Semicolons still required for those statements	README presents snippet as runnable	high	yes
16	Orphan old-syntax sample	completed	examples/containers_json.astr	Previously used old fn main() -> Int and .astr extension; file has been removed	Pre-migration artifact that is now deleted	No docs/test integration indicating active support	high	completed
17	Field type style docs vs formatter/corpus	conflicting	language-syntax-book.md, parser.py, formatter.py, stdlib/	Doc says field/local name: Type; parser accepts both and formatter emits name Type for fields	Canonical output favors no colon for fields	Doc prescribes colon form	medium	yes
Prioritized shortlist (high-confidence, grouped by severity)
Design contradiction

Nullable-union model vs Option<T> model split (not fully interchangeable).
std.core documents generic Option<T>/Result<T,E> variants, but declarations are non-generic in source.
Main compiler language and bundled VS Code compiler language are materially different while bundled mode is default.
Stale feature

let/fixed still present in root spec, tour, diagnostics wording, syntax grammar, and editor grammar.
impl still present in old spec/editor fork though removed from main compiler.
examples/containers_json.astr orphan file has been removed.
Partial migration

-> declaration syntax migration completed across all tooling and documentation.
Try operator changed to !; residual ? references remain in status/spec-compliance/runtime message text.
panic builtin parity gap: semantic+LLVM yes, Python backend no.
Dead/orphaned path

VS Code bundled stdlib missing key modules (thread, sync, channel) and heavily drifted from main stdlib.
Old bundled CLI selfhost message still says placeholder file copier.
Docs/code mismatch

SPEC.md + docs/SPEC_COMPLIANCE.md no longer describe the active frontend.
docs/language/modules.md says imported symbol loading is limited, but semantic/build do recursive loading.
docs/reference-manual.md selfhost statement conflicts with current staged prototype + gated CLI message.
README quick example is not parser-valid as written.
Cleanup recommendations
Issue	Recommendation
let/fixed drift across docs/tooling	completed
-> signature drift across docs/snippets/check/LSP	completed
impl references in stale artifacts	remove
! vs ? references	finish migration
Dual spec conflict (SPEC.md vs active docs/code)	needs design decision
Missing formal docs for trait/is/attrs/gpu fn	document properly
Nullable unions vs Option<T> dual model	needs design decision
std.core Option/Result generic declaration mismatch	needs design decision
panic missing in Python backend	finish migration
Main astra/lsp.py and astra/check.py stale UX syntax	finish migration
Bundled VS Code compiler/LSP fork drift	finish migration
Bundled VS Code stdlib missing modules	finish migration
Module-loading status doc stale	document properly
Selfhost status contradictions across docs/paths	document properly
README runnable snippet invalid	document properly
Orphan .astr sample	removed
Field typing style docs vs formatter reality	document properly

