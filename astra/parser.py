from __future__ import annotations

from astra.ast import *
from astra.int_types import parse_int_type_name
from astra.lexer import Token, lex


class ParseError(SyntaxError):
    """Parse-time syntax error raised by parser and recovery logic."""
    pass


BIN_PREC = {
    "??": 1,
    "||": 2,
    "&&": 3,
    "|": 4,
    "^": 5,
    "&": 6,
    "==": 7,
    "!=": 7,
    "<": 8,
    "<=": 8,
    ">": 8,
    ">=": 8,
    "<<": 9,
    ">>": 9,
    "+": 10,
    "-": 10,
    "*": 11,
    "/": 11,
    "%": 11,
}

ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}


def _diag(code: str, filename: str, line: int, col: int, msg: str) -> str:
    """Format a stable compiler diagnostic string with span info."""
    return f"{code} {filename}:{line}:{col}: {msg}"


def _parse_int_literal(text: str) -> int:
    """Parse decimal/hex/binary integer literal text into an int."""
    t = text.replace("_", "")
    if t.startswith(("0x", "0X")):
        return int(t[2:], 16)
    if t.startswith(("0b", "0B")):
        return int(t[2:], 2)
    return int(t, 10)


def _parse_float_literal(text: str) -> float:
    """Parse a float literal string supporting underscore separators."""
    return float(text.replace("_", ""))


class Parser:
    """Recursive-descent parser for ASTRA source tokens."""
    def __init__(self, src: str, filename: str = "<input>"):
        self.filename = filename
        self.toks = lex(src, filename=filename)
        self.i = 0
        self.errors: list[str] = []
        for tok in self.toks:
            if tok.kind == "ERROR":
                self.errors.append(_diag("LEX", self.filename, tok.line, tok.col, tok.text))

    def cur(self) -> Token:
        return self.toks[self.i]

    def peek(self, n: int = 1) -> Token:
        idx = min(self.i + n, len(self.toks) - 1)
        return self.toks[idx]

    def _err(self, msg: str, tok: Token | None = None) -> None:
        t = tok or self.cur()
        self.errors.append(_diag("PARSE", self.filename, t.line, t.col, msg))

    def eat(self, kind: str) -> Token:
        t = self.cur()
        if t.kind != kind:
            self._err(f"expected {kind}, got {t.kind}", t)
            raise ParseError(self.errors[-1])
        self.i += 1
        return t

    def opt(self, kind: str) -> Token | None:
        if self.cur().kind == kind:
            tok = self.cur()
            self.i += 1
            return tok
        return None

    def _consume_doc_comments(self) -> str:
        lines: list[str] = []
        while self.cur().kind == "DOC_COMMENT":
            lines.append(self.cur().text)
            self.i += 1
        return "\n".join(lines)

    def recover(self) -> None:
        sync = {";", "}", "fn", "impl", "struct", "enum", "type", "import", "extern", "pub", "async", "unsafe", "comptime", "EOF"}
        start = self.i
        while self.cur().kind not in sync:
            self.i += 1
        if self.cur().kind in {";", "}"}:
            self.i += 1
        elif self.i == start and self.cur().kind != "EOF":
            # Ensure forward progress at sync tokens that aren't directly consumed.
            self.i += 1

    def parse_program(self) -> Program:
        items: list[Any] = []
        while self.cur().kind != "EOF":
            doc = self._consume_doc_comments()
            if self.cur().kind == "EOF":
                break
            if self.cur().kind == ";":
                self.i += 1
                continue
            try:
                item = self.parse_top_level(doc)
                if item is not None:
                    items.append(item)
            except ParseError:
                self.recover()
        if self.errors:
            raise ParseError("\n".join(self.errors))
        return Program(items)


    def _assert_attrs_allowed_on(
        self,
        decl_kind: str,
        *,
        is_unsafe: bool,
        is_async: bool,
        is_packed: bool,
        is_multiversion: bool,
        is_impl: bool,
    ) -> None:
        if decl_kind in {"import", "struct", "enum", "type alias"} and (is_unsafe or is_async):
            if decl_kind == "import":
                self._err("import cannot be prefixed with unsafe/async")
            elif decl_kind == "struct":
                self._err("struct cannot be prefixed with unsafe/async")
            elif decl_kind == "enum":
                self._err("enum cannot be prefixed with unsafe/async")
            elif decl_kind == "type alias":
                self._err("type alias cannot be prefixed with unsafe/async")
            raise ParseError(self.errors[-1])
        if decl_kind == "extern" and is_async:
            self._err("extern fn cannot be prefixed with async")
            raise ParseError(self.errors[-1])
        if is_packed and decl_kind != "struct":
            self._err("@packed is only valid on struct declarations")
            raise ParseError(self.errors[-1])
        if is_multiversion and decl_kind != "fn":
            self._err("@multiversion is only valid on fn declarations")
            raise ParseError(self.errors[-1])
        if is_impl and decl_kind != "fn":
            self._err("impl is only valid on fn declarations")
            raise ParseError(self.errors[-1])

    def parse_top_level(self, doc: str):
        is_pub = False
        is_unsafe = False
        is_async = False
        is_impl = False
        is_packed = False
        is_multiversion = False
        while True:
            if self.opt("pub"):
                is_pub = True
                continue
            if self.opt("unsafe"):
                is_unsafe = True
                continue
            if self.opt("async"):
                is_async = True
                continue
            if self.opt("impl"):
                is_impl = True
                continue
            if self.opt("@"):
                attr = self.eat("IDENT").text
                if attr == "packed":
                    is_packed = True
                    continue
                if attr == "multiversion":
                    is_multiversion = True
                    continue
                self._err(f"unknown attribute @{attr}")
                raise ParseError(self.errors[-1])
            break
        if self.cur().kind == "import":
            self._assert_attrs_allowed_on(
                "import",
                is_unsafe=is_unsafe,
                is_async=is_async,
                is_packed=is_packed,
                is_multiversion=is_multiversion,
                is_impl=is_impl,
            )
            return self.parse_import()
        if self.cur().kind == "struct":
            self._assert_attrs_allowed_on(
                "struct",
                is_unsafe=is_unsafe,
                is_async=is_async,
                is_packed=is_packed,
                is_multiversion=is_multiversion,
                is_impl=is_impl,
            )
            return self.parse_struct(is_pub, doc, packed=is_packed)
        if self.cur().kind == "enum":
            self._assert_attrs_allowed_on(
                "enum",
                is_unsafe=is_unsafe,
                is_async=is_async,
                is_packed=is_packed,
                is_multiversion=is_multiversion,
                is_impl=is_impl,
            )
            return self.parse_enum(is_pub, doc)
        if self.cur().kind == "type":
            self._assert_attrs_allowed_on(
                "type alias",
                is_unsafe=is_unsafe,
                is_async=is_async,
                is_packed=is_packed,
                is_multiversion=is_multiversion,
                is_impl=is_impl,
            )
            return self.parse_type_alias()
        if self.cur().kind == "extern":
            self._assert_attrs_allowed_on(
                "extern",
                is_unsafe=is_unsafe,
                is_async=is_async,
                is_packed=is_packed,
                is_multiversion=is_multiversion,
                is_impl=is_impl,
            )
            return self.parse_extern_fn(is_pub, is_unsafe, doc)
        if self.cur().kind == "fn":
            self._assert_attrs_allowed_on(
                "fn",
                is_unsafe=is_unsafe,
                is_async=is_async,
                is_packed=is_packed,
                is_multiversion=is_multiversion,
                is_impl=is_impl,
            )
            return self.parse_fn(is_pub, is_async, doc, is_impl=is_impl, is_unsafe=is_unsafe, multiversion=is_multiversion)
        if is_impl:
            self._err("impl must be followed by fn")
            raise ParseError(self.errors[-1])
        self._err(f"unexpected top-level token {self.cur().kind}")
        raise ParseError(self.errors[-1])

    def parse_import(self) -> ImportDecl:
        tok = self.eat("import")
        path: list[str] = []
        source: str | None = None
        if self.cur().kind == "STR":
            source = self.eat("STR").text
        else:
            path.append(self.eat("IDENT").text)
            while True:
                if self.opt("::") or self.opt("."):
                    path.append(self.eat("IDENT").text)
                    continue
                break
        alias = None
        if self.opt("as"):
            alias = self.eat("IDENT").text
        self.opt(";")
        return ImportDecl(path, alias, tok.pos, tok.line, tok.col, source=source)

    def _parse_generics(self) -> list[str]:
        generics: list[str] = []
        if self.cur().kind != "<":
            return generics
        if self.peek().kind != "IDENT":
            return generics
        self.eat("<")
        generics.append(self.eat("IDENT").text)
        while self.opt(","):
            generics.append(self.eat("IDENT").text)
        self.eat(">")
        return generics

    def _parse_params(self) -> list[tuple[str, str]]:
        params: list[tuple[str, str]] = []
        self.eat("(")
        if self.cur().kind != ")":
            params.append(self._parse_named_type())
            while self.opt(","):
                if self.cur().kind == ")":
                    break
                params.append(self._parse_named_type())
        self.eat(")")
        return params

    def _parse_named_type(self) -> tuple[str, str]:
        name = self.eat("IDENT").text
        self.opt(":")
        typ = self.parse_type()
        return name, typ

    def parse_extern_fn(self, is_pub: bool, is_unsafe: bool, doc: str) -> ExternFnDecl:
        tok = self.eat("extern")
        lib_tok = self.cur()
        if lib_tok.kind == "STR":
            self.i += 1
            lib = lib_tok.text
        elif lib_tok.kind == "IDENT":
            self.i += 1
            lib = lib_tok.text
        else:
            self._err("extern requires a library name string", lib_tok)
            raise ParseError(self.errors[-1])
        self.eat("fn")
        name_tok = self.eat("IDENT")
        params = self._parse_params()
        self.eat("->")
        ret = self.parse_type()
        self.eat(";")
        return ExternFnDecl(
            lib=lib,
            name=name_tok.text,
            params=params,
            ret=ret,
            unsafe=is_unsafe,
            pub=is_pub,
            doc=doc,
            pos=tok.pos,
            line=tok.line,
            col=tok.col,
        )

    def parse_fn(
        self,
        is_pub: bool = False,
        is_async: bool = False,
        doc: str = "",
        is_impl: bool = False,
        is_unsafe: bool = False,
        multiversion: bool = False,
    ) -> FnDecl:
        fn_tok = self.eat("fn")
        name = self.eat("IDENT").text
        generics = self._parse_generics()
        params = self._parse_params()
        self.eat("->")
        ret = self.parse_type()
        where = self._parse_where_constraints()
        body = self.parse_block()
        return FnDecl(
            name,
            generics,
            params,
            ret,
            body,
            where=where,
            is_impl=is_impl,
            pub=is_pub,
            async_fn=is_async,
            unsafe=is_unsafe,
            multiversion=multiversion,
            doc=doc,
            pos=fn_tok.pos,
            line=fn_tok.line,
            col=fn_tok.col,
        )

    def _parse_where_constraints(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        if not self.opt("where"):
            return out
        while True:
            tvar = self.eat("IDENT")
            self.eat(":")
            traits = [self.eat("IDENT").text]
            while self.opt("+"):
                traits.append(self.eat("IDENT").text)
            out[tvar.text] = traits
            if not self.opt(","):
                break
        return out

    def parse_struct(self, is_pub: bool = False, doc: str = "", packed: bool = False) -> StructDecl:
        tok = self.eat("struct")
        name = self.eat("IDENT").text
        generics = self._parse_generics()
        self.eat("{")
        fields: list[tuple[str, str]] = []
        while self.cur().kind != "}":
            fields.append(self._parse_named_type())
            self.opt(",")
        self.eat("}")
        return StructDecl(name, generics, fields, [], pub=is_pub, packed=packed, doc=doc, pos=tok.pos, line=tok.line, col=tok.col)

    def parse_enum(self, is_pub: bool = False, doc: str = "") -> EnumDecl:
        tok = self.eat("enum")
        name = self.eat("IDENT").text
        generics = self._parse_generics()
        self.eat("{")
        variants: list[tuple[str, list[str]]] = []
        while self.cur().kind != "}":
            vname = self.eat("IDENT").text
            vtypes: list[str] = []
            if self.opt("("):
                if self.cur().kind != ")":
                    vtypes.append(self.parse_type())
                    while self.opt(","):
                        vtypes.append(self.parse_type())
                self.eat(")")
            variants.append((vname, vtypes))
            self.opt(",")
        self.eat("}")
        return EnumDecl(name, generics, variants, pub=is_pub, doc=doc, pos=tok.pos, line=tok.line, col=tok.col)

    def parse_type_alias(self) -> TypeAliasDecl:
        tok = self.eat("type")
        name = self.eat("IDENT").text
        generics = self._parse_generics()
        self.eat("=")
        target = self.parse_type()
        self.opt(";")
        return TypeAliasDecl(name, generics, target, tok.pos, tok.line, tok.col)

    def parse_type(self):
        typ: str
        if self.opt("&"):
            mut = "mut " if self.opt("mut") else ""
            typ = f"&{mut}{type_text(self.parse_type())}"
        elif self.opt("["):
            inner = self.parse_type()
            self.eat("]")
            typ = f"[{type_text(inner)}]"
        elif self.opt("fn"):
            self.eat("(")
            args: list[str] = []
            if self.cur().kind != ")":
                args.append(type_text(self.parse_type()))
                while self.opt(","):
                    args.append(type_text(self.parse_type()))
            self.eat(")")
            self.eat("->")
            typ = f"fn({', '.join(args)}) -> {type_text(self.parse_type())}"
        else:
            if self.cur().kind in {"IDENT", "INT_TYPE"}:
                tok_kind = self.cur().kind
                name = self.cur().text
                self.i += 1
            else:
                self._err(f"expected type name, got {self.cur().kind}", self.cur())
                raise ParseError(self.errors[-1])
            if tok_kind == "INT_TYPE":
                int_info = parse_int_type_name(name)
                if int_info is not None:
                    bits, signed = int_info
                    typ = str(ArbitraryIntType(signed=signed, width=bits))
                else:
                    typ = name
            else:
                typ = name
            if self.opt("<"):
                args = [type_text(self.parse_type())]
                while self.opt(","):
                    args.append(type_text(self.parse_type()))
                self.eat(">")
                typ = f"{name}<{', '.join(args)}>"
        while self.opt("?"):
            typ = f"Option<{type_text(typ)}>"
        return typ

    def parse_block(self) -> list[Any]:
        self.eat("{")
        body: list[Any] = []
        while self.cur().kind != "}":
            if self.cur().kind == "EOF":
                self._err("unexpected EOF while parsing block")
                raise ParseError(self.errors[-1])
            if self.cur().kind == "DOC_COMMENT":
                self.i += 1
                continue
            try:
                body.append(self.parse_stmt())
            except ParseError:
                prev = self.i
                self.recover()
                if self.i == prev:
                    raise
        self.eat("}")
        return body

    def parse_stmt(self):
        tok = self.cur()
        if self.cur().kind in {"let", "fixed"}:
            is_fixed = self.eat(self.cur().kind).kind == "fixed"
            is_mut = bool(self.opt("mut"))
            if is_fixed and is_mut:
                self._err("fixed bindings cannot be mutable", tok)
                raise ParseError(self.errors[-1])
            name_tok = self.eat("IDENT")
            type_name = None
            if self.opt(":"):
                type_name = self.parse_type()
            self.eat("=")
            expr = self.parse_expr()
            self.eat(";")
            return LetStmt(name_tok.text, expr, is_mut, type_name, tok.pos, tok.line, tok.col, fixed=is_fixed)
        if self.opt("return"):
            if self.opt(";"):
                return ReturnStmt(None, tok.pos, tok.line, tok.col)
            e = self.parse_expr()
            self.eat(";")
            return ReturnStmt(e, tok.pos, tok.line, tok.col)
        if self.opt("break"):
            self.eat(";")
            return BreakStmt(tok.pos, tok.line, tok.col)
        if self.opt("continue"):
            self.eat(";")
            return ContinueStmt(tok.pos, tok.line, tok.col)
        if self.opt("defer"):
            e = self.parse_expr()
            self.eat(";")
            return DeferStmt(e, tok.pos, tok.line, tok.col)
        if self.opt("drop"):
            e = self.parse_expr()
            self.eat(";")
            return DropStmt(e, tok.pos, tok.line, tok.col)
        if self.opt("comptime"):
            body = self.parse_block()
            return ComptimeStmt(body, tok.pos, tok.line, tok.col)
        if self.opt("if"):
            cond = self.parse_expr()
            then_body = self.parse_block()
            else_body = []
            if self.opt("else"):
                else_body = self.parse_block()
            return IfStmt(cond, then_body, else_body, tok.pos, tok.line, tok.col)
        if self.opt("while"):
            cond = self.parse_expr()
            body = self.parse_block()
            return WhileStmt(cond, body, tok.pos, tok.line, tok.col)
        if self.opt("for"):
            return self.parse_for(tok)
        if self.opt("match"):
            return self.parse_match(tok)
        if self.opt("unsafe"):
            body = self.parse_block()
            return UnsafeStmt(body, tok.pos, tok.line, tok.col)

        lhs = self.parse_expr()
        if self.cur().kind in ASSIGN_OPS:
            op = self.eat(self.cur().kind).kind
            expr = self.parse_expr()
            self.eat(";")
            return AssignStmt(lhs, op, expr, tok.pos, tok.line, tok.col)
        self.eat(";")
        return ExprStmt(lhs, tok.pos, tok.line, tok.col)

    def parse_for(self, tok: Token) -> ForStmt:
        if self.cur().kind == "IDENT" and self.peek().kind == "in":
            ident = self.eat("IDENT")
            self.eat("in")
            start_expr = self.parse_expr()
            if self.opt(".."):
                dots_tok = self.toks[self.i - 1]
                inclusive = bool(self.opt("="))
                end_expr = self.parse_expr()
                idx_name = ident.text
                init = LetStmt(idx_name, start_expr, True, None, ident.pos, ident.line, ident.col)
                cond = Binary(
                    "<=" if inclusive else "<",
                    Name(idx_name, ident.pos, ident.line, ident.col),
                    end_expr,
                    dots_tok.pos,
                    dots_tok.line,
                    dots_tok.col,
                )
                step = AssignStmt(
                    Name(idx_name, ident.pos, ident.line, ident.col),
                    "+=",
                    Literal(1, dots_tok.pos, dots_tok.line, dots_tok.col),
                    dots_tok.pos,
                    dots_tok.line,
                    dots_tok.col,
                )
                # Parse body and ensure `continue` doesn't skip the implicit step in backends
                # that emit the step at the end of the loop body.
                body = self.parse_block()

                def _make_step_stmt() -> AssignStmt:
                    return AssignStmt(
                        Name(idx_name, ident.pos, ident.line, ident.col),
                        "+=",
                        Literal(1, dots_tok.pos, dots_tok.line, dots_tok.col),
                        dots_tok.pos,
                        dots_tok.line,
                        dots_tok.col,
                    )

                def _patch_continues(stmts: list[Any]) -> list[Any]:
                    out: list[Any] = []
                    for s in stmts:
                        # Do not descend into nested loops: their `continue` targets the inner loop.
                        if isinstance(s, (WhileStmt, ForStmt)):
                            out.append(s)
                            continue

                        if isinstance(s, ContinueStmt):
                            out.append(_make_step_stmt())
                            out.append(s)
                            continue

                        if isinstance(s, IfStmt):
                            s.then_body = _patch_continues(s.then_body)
                            s.else_body = _patch_continues(s.else_body)
                            out.append(s)
                            continue

                        if isinstance(s, MatchStmt):
                            s.arms = [(pat, _patch_continues(arm_body)) for (pat, arm_body) in s.arms]
                            out.append(s)
                            continue

                        if isinstance(s, UnsafeStmt):
                            s.body = _patch_continues(s.body)
                            out.append(s)
                            continue

                        if isinstance(s, ComptimeStmt):
                            s.body = _patch_continues(s.body)
                            out.append(s)
                            continue

                        out.append(s)
                    return out

                body = _patch_continues(body)

                # Keep the normal end-of-iteration step for non-continue paths.
                step = _make_step_stmt()
                return ForStmt(init, cond, step, body, tok.pos, tok.line, tok.col)
            self._err("for-in currently supports only range syntax `start..end` or `start..=end`", self.cur())
            raise ParseError(self.errors[-1])
        init = None
        if self.cur().kind != ";":
            if self.cur().kind in {"let", "fixed"}:
                init = self.parse_stmt()
            else:
                init = self.parse_expr()
                self.eat(";")
        else:
            self.eat(";")
        cond = None
        if self.cur().kind != ";":
            cond = self.parse_expr()
        self.eat(";")
        step = None
        if self.cur().kind != "{":
            lhs = self.parse_expr()
            if self.cur().kind in ASSIGN_OPS:
                op = self.eat(self.cur().kind).kind
                rhs = self.parse_expr()
                step = AssignStmt(lhs, op, rhs, tok.pos, tok.line, tok.col)
            else:
                step = lhs
        body = self.parse_block()
        return ForStmt(init, cond, step, body, tok.pos, tok.line, tok.col)

    def parse_match(self, tok: Token) -> MatchStmt:
        expr = self.parse_expr()
        self.eat("{")
        arms: list[tuple[Any, list[Any]]] = []
        while self.cur().kind != "}":
            pattern = self.parse_match_pattern()
            if self.opt("if"):
                iftok = self.toks[self.i - 1]
                cond = self.parse_expr()
                pattern = GuardPattern(pattern, cond, iftok.pos, iftok.line, iftok.col)
            self.eat("=>")
            body = self.parse_block()
            arms.append((pattern, body))
            self.opt(",")
        self.eat("}")
        return MatchStmt(expr, arms, tok.pos, tok.line, tok.col)

    def parse_match_pattern(self):
        tok = self.cur()
        if tok.kind == "IDENT" and tok.text == "_":
            wtok = self.eat("IDENT")
            return WildcardPattern(wtok.pos, wtok.line, wtok.col)

        if tok.kind == "IDENT" and self.peek().kind == "." and self.peek(2).kind == "IDENT":
            enum_tok = self.eat("IDENT")
            self.eat(".")
            var_tok = self.eat("IDENT")
            args: list[Any] = []
            if self.opt("("):
                if self.cur().kind != ")":
                    while True:
                        args.append(self.parse_match_pattern())
                        if not self.opt(","):
                            break
                self.eat(")")
            return VariantPattern(enum_tok.text, var_tok.text, args, enum_tok.pos, enum_tok.line, enum_tok.col)

        if tok.kind == "IDENT":
            btok = self.eat("IDENT")
            return BindPattern(btok.text, btok.pos, btok.line, btok.col)

        return self.parse_expr()

    def parse_expr(self, min_prec: int = 1):
        left = self.parse_cast()
        while self.cur().kind in BIN_PREC and BIN_PREC[self.cur().kind] >= min_prec:
            op_tok = self.eat(self.cur().kind)
            prec = BIN_PREC[op_tok.kind]
            right = self.parse_expr(prec + 1)
            left = Binary(op_tok.kind, left, right, op_tok.pos, op_tok.line, op_tok.col)
        return left

    def parse_cast(self):
        expr = self.parse_unary()
        while self.opt("as"):
            tok = self.toks[self.i - 1]
            expr = CastExpr(expr, self.parse_type(), tok.pos, tok.line, tok.col)
        return expr

    def parse_unary(self):
        if self.opt("await"):
            tok = self.toks[self.i - 1]
            return AwaitExpr(self.parse_unary(), tok.pos, tok.line, tok.col)
        if self.cur().kind in {"-", "!", "~", "&", "*"}:
            tok = self.eat(self.cur().kind)
            op = tok.kind
            if op == "&" and self.opt("mut"):
                op = "&mut"
            expr = self.parse_unary()
            return Unary(op, expr, tok.pos, tok.line, tok.col)
        return self.parse_postfix()

    def parse_postfix(self):
        expr = self.parse_atom()
        while True:
            if self.opt("."):
                field_tok = self.eat("IDENT")
                expr = FieldExpr(expr, field_tok.text, field_tok.pos, field_tok.line, field_tok.col)
                continue
            if self.opt("["):
                idx = self.parse_expr()
                rb = self.eat("]")
                expr = IndexExpr(expr, idx, rb.pos, rb.line, rb.col)
                continue
            if self.opt("("):
                args: list[Any] = []
                if self.cur().kind != ")":
                    args.append(self.parse_expr())
                    while self.opt(","):
                        args.append(self.parse_expr())
                end = self.eat(")")
                expr = Call(expr, args, end.pos, end.line, end.col)
                continue
            break
        return expr

    def parse_atom(self):
        tok = self.cur()
        if self.opt("sizeof"):
            self.eat("(")
            typ = self.parse_type()
            self.eat(")")
            return SizeOfTypeExpr(typ, tok.pos, tok.line, tok.col)
        if self.opt("alignof"):
            self.eat("(")
            typ = self.parse_type()
            self.eat(")")
            return AlignOfTypeExpr(typ, tok.pos, tok.line, tok.col)
        if self.opt("INT"):
            lit = Literal(_parse_int_literal(tok.text), tok.pos, tok.line, tok.col)
            nxt = self.cur()
            if nxt.kind == "INT_TYPE" and nxt.pos == tok.pos + len(tok.text):
                self.i += 1
                return CastExpr(lit, nxt.text, nxt.pos, nxt.line, nxt.col)
            return lit
        if self.opt("FLOAT"):
            return Literal(_parse_float_literal(tok.text), tok.pos, tok.line, tok.col)
        if self.opt("STR"):
            return Literal(tok.text, tok.pos, tok.line, tok.col)
        if self.opt("STR_MULTI"):
            return Literal(tok.text, tok.pos, tok.line, tok.col)
        if self.opt("CHAR"):
            return Literal(tok.text, tok.pos, tok.line, tok.col)
        if self.opt("BOOL"):
            return BoolLit(tok.text == "true", tok.pos, tok.line, tok.col)
        if self.opt("none"):
            return NilLit(tok.pos, tok.line, tok.col)
        if self.opt("IDENT"):
            if tok.text in {"size_of", "align_of"} and self.cur().kind == "(":
                self.eat("(")
                inner = self.parse_expr()
                self.eat(")")
                if tok.text == "size_of":
                    return SizeOfValueExpr(inner, tok.pos, tok.line, tok.col)
                return AlignOfValueExpr(inner, tok.pos, tok.line, tok.col)
            if tok.text in {"bitSizeOf", "maxVal", "minVal"} and self.cur().kind == "(":
                self.eat("(")
                typ = self.parse_type()
                self.eat(")")
                if tok.text == "bitSizeOf":
                    return BitSizeOfTypeExpr(typ, tok.pos, tok.line, tok.col)
                if tok.text == "maxVal":
                    return MaxValTypeExpr(typ, tok.pos, tok.line, tok.col)
                return MinValTypeExpr(typ, tok.pos, tok.line, tok.col)
            return Name(tok.text, tok.pos, tok.line, tok.col)
        if self.opt("["):
            elems = []
            if self.cur().kind != "]":
                elems.append(self.parse_expr())
                while self.opt(","):
                    elems.append(self.parse_expr())
            end = self.eat("]")
            return ArrayLit(elems, end.pos, end.line, end.col)
        if self.opt("("):
            e = self.parse_expr()
            self.eat(")")
            return e
        self._err(f"unexpected atom {self.cur().kind}")
        raise ParseError(self.errors[-1])


def parse(src: str, filename: str = "<input>"):
    """Parse source text into a Program AST."""
    return Parser(src, filename=filename).parse_program()
