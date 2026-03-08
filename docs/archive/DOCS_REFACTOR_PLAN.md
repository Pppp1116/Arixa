# Documentation Refactor Plan

This plan outlines the restructuring and cleanup of ASTRA documentation based on the implementation audit findings.

## Current Documentation Structure Analysis

### Existing Documentation Files

**Primary Documentation**:
- `README.md` - Project overview (6.2KB)
- `docs/README.md` - Documentation index (4.2KB)
- `docs/language/specification.md` - Language specification (9.1KB)
- `docs/language/` - Language reference docs (14 files)

**Archive Documentation** (to be cleaned up):
- `docs/archive/` - 13 files with outdated information
- Multiple old specifications and migration guides

**Specialized Documentation**:
- `docs/compiler/` - 9 files on compiler internals
- `docs/gpu/` - 13 files on GPU computing
- `docs/stdlib/` - 29 files on standard library
- `docs/development/` - 7 files on development
- `docs/tooling/` - 4 files on tools

## Problems Identified

### 1. Naming Inconsistency
- Repository: "ASTRA"
- README: "Arixa"  
- File extension: `.arixa`
- Tool names: `ar*` prefix (consistent with "arixa")

### 2. Documentation Proliferation
- Multiple overlapping specifications
- Outdated migration guides in archive/
- Inconsistent terminology across files
- Duplicate information spread across multiple files

### 3. Documentation-Implementation Gaps
- Docs claim `let` keyword exists - implementation doesn't use it
- Missing documentation for enhanced loop forms
- Ownership system poorly documented despite comprehensive implementation

## Refactor Strategy

### Phase 1: Resolve Naming Consistency

**Decision Point**: Choose between "ASTRA" and "Arixa"

**Recommendation**: Use "ASTRA" consistently because:
- Repository name is ASTRA
- Most internal references use ASTRA
- Tool names can be updated to `astra*` prefix

**Actions Required**:
1. Update README.md title from "Arixa" to "ASTRA"
2. Update all documentation references from "Arixa" to "ASTRA"
3. Update file extensions from `.arixa` to `.astra` (or document the inconsistency)
4. Update tool names from `ar*` to `astra*` in documentation

### Phase 2: Documentation Consolidation

#### Keep These Core Files (Update and Expand):
1. `README.md` - Main project overview
2. `docs/language/specification.md` - Single source of truth language spec
3. `docs/language/getting-started.md` - User introduction
4. `docs/language/reference.md` - Comprehensive language reference
5. `docs/stdlib/README.md` - Standard library overview
6. `docs/compiler/README.md` - Compiler architecture overview

#### Merge These Files:
1. **Language Reference**: Combine content from:
   - `docs/language/syntax.md`
   - `docs/language/control_flow.md`
   - `docs/language/tour.md`
   - `docs/language/types.md`
   - Into single comprehensive `docs/language/reference.md`

2. **Standard Library Reference**: Consolidate:
   - Individual module docs in `docs/stdlib/`
   - Keep module-specific docs only for complex modules
   - Use `stdlib/README.md` as main index

#### Archive/Delete These Files:
1. **Archive Directory** - Move to `docs/legacy/`:
   - `docs/archive/SYNTAX_MIGRATION_GUIDE.md`
   - `docs/archive/SYNTAX_ENHANCEMENT_COMPARISON.md`
   - `docs/archive/old_language_spec.md`
   - `docs/archive/old_syntax_book.md`
   - `docs/archive/old_reference_manual.md`

2. **Delete Outdated Files**:
   - `docs/archive/FINAL_IMPLEMENTATION_STATUS.md` (status tracking, not reference)
   - `docs/archive/BACKEND_IMPLEMENTATION_STATUS.md` (status tracking)
   - Duplicate implementation status files

### Phase 3: Content Updates

#### Update Language Specification (`docs/language/specification.md`):
1. **Remove incorrect keyword references**:
   - Remove `let` from keyword list
   - Remove `const` from keyword list
   - Update grammar to reflect actual parser implementation

2. **Add missing features**:
   - Enhanced while loops: `while mut x = condition { }`
   - Iterator for loops: `for item in iterable { }`
   - Ownership system documentation
   - Borrow checking rules

3. **Clarify binding syntax**:
   - Document identifier-based binding (`name = expr`)
   - Document mutable binding (`mut name = expr`)
   - Document explicit reassignment (`set name = expr`)

#### Create Comprehensive Language Reference (`docs/language/reference.md`):
1. **Statements Section**:
   - All statement types with examples
   - Enhanced loop forms
   - Ownership and borrowing

2. **Expressions Section**:
   - Operator precedence table
   - Type casting with `as`
   - Option coalescing `??`
   - Range expressions

3. **Types Section**:
   - All primitive types
   - Composite types
   - Type inference rules

4. **Memory Management Section**:
   - Ownership model
   - Borrow checking
   - Lifetime rules

#### Update Main README.md:
1. Fix project name: "ASTRA" instead of "Arixa"
2. Update example to use consistent naming
3. Fix documentation references
4. Add note about file extension inconsistency

### Phase 4: Standard Library Documentation

#### Consolidate Stdlib Docs:
1. **Keep**: `docs/stdlib/README.md` as main index
2. **Keep**: Documentation for complex modules (crypto, gpu, etc.)
3. **Simplify**: Remove redundant docs for simple modules
4. **Standardize**: Use consistent format across all module docs

#### Update Stdlib Content:
1. Fix naming consistency (ASTRA vs Arixa)
2. Update examples to use correct syntax
3. Document freestanding vs hosted distinction clearly

### Phase 5: Tooling and Development Documentation

#### Reorganize Development Docs:
1. **Consolidate**: `docs/development/` content
2. **Update**: Tool names and commands
3. **Add**: Contributing guidelines if missing
4. **Archive**: Outdated development guides

## New Documentation Structure

```
docs/
├── README.md                    # Documentation index
├── language/
│   ├── specification.md         # Single source of truth spec
│   ├── getting-started.md       # User introduction
│   ├── reference.md            # Comprehensive language reference
│   └── memory-safety.md        # Ownership and borrowing deep dive
├── stdlib/
│   ├── README.md               # Stdlib overview and index
│   └── [module-specific docs]  # Only for complex modules
├── compiler/
│   └── README.md               # Compiler architecture overview
├── gpu/
│   └── README.md               # GPU computing guide
├── tools/
│   └── README.md               # Tooling overview
├── development/
│   ├── getting-started.md      # Development setup
│   ├── contributing.md         # Contribution guidelines
│   └── architecture.md         # Development architecture
└── legacy/                     # Renamed from archive/
    ├── old_language_spec.md
    ├── migration_guides/
    └── implementation_status/
```

## Implementation Timeline

### Week 1: Naming Consistency
- [ ] Decide on final name (ASTRA recommended)
- [ ] Update README.md
- [ ] Update main documentation headers
- [ ] Document file extension decision

### Week 2: Core Documentation Updates
- [ ] Update language specification
- [ ] Create comprehensive language reference
- [ ] Update stdlib overview
- [ ] Fix examples and code snippets

### Week 3: Consolidation
- [ ] Merge overlapping language docs
- [ ] Move outdated docs to legacy/
- [ ] Delete redundant files
- [ ] Update all internal links

### Week 4: Review and Finalize
- [ ] Review all updated documentation
- [ ] Check for consistency
- [ ] Validate against implementation
- [ ] Update documentation index

## Risk Mitigation

### High-Risk Changes:
1. **File extension change** (.arixa → .astra) - Could break existing tooling
2. **Tool name changes** (ar* → astra*) - Could affect user workflows
3. **Documentation deletion** - Could lose useful information

### Mitigation Strategies:
1. **Document inconsistencies** rather than changing code initially
2. **Move to legacy/ instead of deleting** when uncertain
3. **Provide migration guides** for breaking changes
4. **Maintain backward compatibility** where possible

## Success Metrics

1. **Consistency**: All references use same language name
2. **Accuracy**: Documentation matches implementation
3. **Completeness**: All implemented features documented
4. **Clarity**: Single source of truth for each topic
5. **Maintainability**: Clear documentation structure

## Next Steps

1. **Get stakeholder approval** on naming decision
2. **Create backup** of current documentation
3. **Implement Phase 1** (naming consistency)
4. **Proceed with remaining phases** based on feedback
5. **Create migration guide** for any breaking changes

This refactor prioritizes accuracy over completeness, ensuring that documentation reflects the actual implementation rather than aspirational features.
