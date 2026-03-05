# Parser

Implementation: `astra/parser.py`

Parser style:

- recursive descent
- precedence-aware expression parsing
- synchronization-based error recovery for multi-error reporting

Main API:

- `Parser` class
- `parse(src, filename=...)`
- `ParseError`

Output:

- `Program` AST populated with top-level declarations and statement/expression trees.
