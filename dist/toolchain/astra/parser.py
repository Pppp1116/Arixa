"""Recursive-descent parser that turns tokens into AST declarations/statements."""

from __future__ import annotations

from astra.ast import *
from astra.int_types import parse_int_type_name
from astra.lexer import Token, lex


class ParseError(SyntaxError):
    """Error type raised by the parser subsystem.
    
    This type is part of Astra's public compiler/tooling surface.
    """
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
    return f"{code} {filename}:{line}:{col}: {msg}"


def _parse_int_literal(text: str) -> int:
    t = text.replace("_", "")
    if t.startswith(("0x", "0X")):
        return int(t[2:], 16)
    if t.startswith(("0b", "0B")):
        return int(t[2:], 2)
    return int(t, 10)


def _parse_float_literal(text: str) -> float:
    return float(text.replace("_", ""))


class Parser:
    """Data container used by parser.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    def __init__(self, src: str, filename: str = "<input>"):
        self.filename = filename
        self.toks = lex(src, filename=filename)
        self.i = 0
        self.errors: list[str] = []
        for tok in self.toks:
            if tok.kind == "ERROR":
                self.errors.append(_diag("LEX", self.filename, tok.line, tok.col, tok.text))

    def cur(self) -> Token:
        """Return the current token without advancing.
        
        Parameters:
            none
        
        Returns:
            Value described by the function return annotation.
        """
        return self.toks[self.i]

    def peek(self, n: int = 1) -> Token:
        """Return a lookahead token relative to the current cursor.
        
        Parameters:
            n: Input value used by this function.
        
        Returns:
            Value described by the function return annotation.
        """
        idx = min(self.i + n, len(self.toks) - 1)
        return self.toks[idx]

    def _err(self, msg: str, tok: Token | None = None) -> None:
        t = tok or self.cur()
        self.errors.append(_diag("PARSE", self.filename, t.line, t.col, msg))

    def eat(self, kind: str) -> Token:
        """Consume and return the expected token kind or raise ParseError.
        
        Parameters:
            kind: Input value used by this function.
        
        Returns:
            Value described by the function return annotation.
        """
        t = self.cur()
        if t.kind != kind:
            self._err(f"expected {kind}, got {t.kind}", t)
            raise ParseError(self.errors[-1])
        self.i += 1
        return t

    def opt(self, kind: str) -> Token | None:
        """Consume and return a token when the expected kind is present.
        
        Parameters:
            kind: Input value used by this function.
        
        Returns:
            Value described by the function return annotation.
        """
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
        """Advance the parser to the next synchronization point after an error.
        
        Parameters:
            none
        
        Returns:
            Value described by the function return annotation.
        """
        sync = {
            ";",
            "}",
            "fn",
            "struct",
            "enum",
            "type",
            "import",
            "extern",
            "let",
            "fixed",
            "pub",
            "async",
            "unsafe",
            "comptime",
            "EOF",
        }
        start = self.i
        while self.cur().kind not in sync:
            self.i += 1
        if self.cur().kind in {";", "}"}:
            self.i += 1
        elif self.i == start and self.cur().kind != "EOF":
            # Ensure forward progress even when the failing token is a sync token.
            self.i += 1

    def parse_program(self) -> Program:
        """Parse the `program` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value described by the function return annotation.
        """
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

    def parse_top_level(self, doc: str):
        """Parse the `top_level` grammar production from the token stream.
        
        Parameters:
            doc: Input value used by this function.
        
        Returns:
            Value produced by the function, if any.
        """
        is_pub = False
        is_unsafe = False
        is_async = False
        is_packed = False
        link_libs: list[str] = []
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
            if self.opt("@"):
                attr = self.eat("IDENT").text
                if attr == "packed":
                    is_packed = True
                    continue
                if attr == "link":
                    self.eat("(")
                    lib_tok = self.cur()
                    if lib_tok.kind != "STR":
                        self._err("@link expects a string literal, for example @link(\"SDL2\")", lib_tok)
                        raise ParseError(self.errors[-1])
                    self.i += 1
                    self.eat(")")
                    link_libs.append(lib_tok.text)
                    continue
                self._err(f"unknown attribute @{attr}")
                raise ParseError(self.errors[-1])
                continue
            break
        if self.cur().kind == "import":
            if link_libs:
                self._err("@link is only valid on extern function declarations")
                raise ParseError(self.errors[-1])
            if is_unsafe or is_async:
                self._err("import cannot be prefixed with unsafe/async")
                raise ParseError(self.errors[-1])
            if is_packed:
                self._err("@packed is only valid on struct declarations")
                raise ParseError(self.errors[-1])
            return self.parse_import()
        if self.cur().kind == "struct":
            if link_libs:
                self._err("@link is only valid on extern function declarations")
                raise ParseError(self.errors[-1])
            if is_unsafe or is_async:
                self._err("struct cannot be prefixed with unsafe/async")
                raise ParseError(self.errors[-1])
            return self.parse_struct(is_pub, doc, packed=is_packed)
        if self.cur().kind == "enum":
            if link_libs:
                self._err("@link is only valid on extern function declarations")
                raise ParseError(self.errors[-1])
            if is_unsafe or is_async:
                self._err("enum cannot be prefixed with unsafe/async")
                raise ParseError(self.errors[-1])
            if is_packed:
                self._err("@packed is only valid on struct declarations")
                raise ParseError(self.errors[-1])
            return self.parse_enum(is_pub, doc)
        if self.cur().kind == "type":
            if link_libs:
                self._err("@link is only valid on extern function declarations")
                raise ParseError(self.errors[-1])
            if is_unsafe or is_async:
                self._err("type alias cannot be prefixed with unsafe/async")
                raise ParseError(self.errors[-1])
            if is_packed:
                self._err("@packed is only valid on struct declarations")
                raise ParseError(self.errors[-1])
            return self.parse_type_alias()
        if self.cur().kind == "extern":
            if is_packed:
                self._err("@packed is only valid on struct declarations")
                raise ParseError(self.errors[-1])
            return self.parse_extern_fn(is_pub, is_unsafe, doc, link_libs=link_libs)
        if self.cur().kind == "fn":
            if is_packed:
                self._err("@packed is only valid on struct declarations")
                raise ParseError(self.errors[-1])
            if link_libs:
                self._err("@link is only valid on extern function declarations")
                raise ParseError(self.errors[-1])
            return self.parse_fn(is_pub, is_async, doc, is_unsafe=is_unsafe)
        if self.cur().kind in {"let", "fixed"}:
            if link_libs or is_packed or is_pub or is_unsafe or is_async:
                self._err("top-level bindings cannot use declaration modifiers or attributes")
                raise ParseError(self.errors[-1])
            return self.parse_global_binding()
        if link_libs:
            self._err("@link is only valid on extern function declarations")
            raise ParseError(self.errors[-1])
        self._err(f"unexpected top-level token {self.cur().kind}")
        raise ParseError(self.errors[-1])

    def parse_import(self) -> ImportDecl:
        """Parse the `import` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value described by the function return annotation.
        """
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

    def _parse_params(self, *, allow_variadic: bool = False) -> tuple[list[tuple[str, str]], bool]:
        params: list[tuple[str, str]] = []
        variadic = False
        self.eat("(")
        if self.cur().kind != ")":
            if allow_variadic and self.cur().kind == "...":
                self.eat("...")
                variadic = True
            else:
                params.append(self._parse_named_type())
            while self.opt(","):
                if self.cur().kind == ")":
                    break
                if allow_variadic and self.cur().kind == "...":
                    self.eat("...")
                    variadic = True
                    break
                if variadic:
                    self._err("variadic marker `...` must be the last parameter")
                    raise ParseError(self.errors[-1])
                params.append(self._parse_named_type())
            if variadic and self.cur().kind != ")":
                self._err("variadic marker `...` must be the last parameter")
                raise ParseError(self.errors[-1])
        self.eat(")")
        return params, variadic

    def _parse_named_type(self) -> tuple[str, str]:
        name = self.eat("IDENT").text
        self.opt(":")
        typ = self.parse_type()
        return name, typ

    def parse_extern_fn(
        self,
        is_pub: bool,
        is_unsafe: bool,
        doc: str,
        *,
        link_libs: list[str] | None = None,
    ) -> ExternFnDecl:
        """Parse the `extern_fn` grammar production from the token stream.
        
        Parameters:
            is_pub: Input value used by this function.
            is_unsafe: Input value used by this function.
            doc: Input value used by this function.
        
        Returns:
            Value described by the function return annotation.
        """
        tok = self.eat("extern")
        libs = list(link_libs or [])
        # Backward compatibility: accept legacy `extern "lib" fn` / `extern libc fn`.
        if self.cur().kind in {"STR", "IDENT"} and self.peek().kind == "fn":
            libs.append(self.cur().text)
            self.i += 1
        self.eat("fn")
        name_tok = self.eat("IDENT")
        params, is_variadic = self._parse_params(allow_variadic=True)
        self.eat("->")
        ret = self.parse_type()
        self.eat(";")
        return ExternFnDecl(
            name=name_tok.text,
            params=params,
            ret=ret,
            is_variadic=is_variadic,
            link_libs=libs,
            lib=(libs[0] if libs else ""),
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
        is_unsafe: bool = False,
    ) -> FnDecl:
        """Parse the `fn` grammar production from the token stream.
        
        Parameters:
            is_pub: Input value used by this function.
            is_async: Input value used by this function.
            doc: Input value used by this function.
            is_unsafe: Input value used by this function.
        
        Returns:
            Value described by the function return annotation.
        """
        fn_tok = self.eat("fn")
        name = self.eat("IDENT").text
        generics = self._parse_generics()
        params, _ = self._parse_params()
        if self.opt("->"):
            ret = self.parse_type()
        elif name == "main" and not is_impl and not params and not generics:
            ret = "Int"
        else:
            self._err("expected -> return type", self.cur())
            raise ParseError(self.errors[-1])
        body = self.parse_block()
        return FnDecl(
            name,
            generics,
            params,
            ret,
            body,
            pub=is_pub,
            async_fn=is_async,
            unsafe=is_unsafe,
            doc=doc,
            pos=fn_tok.pos,
            line=fn_tok.line,
            col=fn_tok.col,
        )

    def parse_struct(self, is_pub: bool = False, doc: str = "", packed: bool = False) -> StructDecl:
        """Parse the `struct` grammar production from the token stream.
        
        Parameters:
            is_pub: Input value used by this function.
            doc: Input value used by this function.
            packed: Input value used by this function.
        
        Returns:
            Value described by the function return annotation.
        """
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
        """Parse the `enum` grammar production from the token stream.
        
        Parameters:
            is_pub: Input value used by this function.
            doc: Input value used by this function.
        
        Returns:
            Value described by the function return annotation.
        """
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
        """Parse the `type_alias` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value described by the function return annotation.
        """
        tok = self.eat("type")
        name = self.eat("IDENT").text
        generics = self._parse_generics()
        self.eat("=")
        target = self.parse_type()
        self.opt(";")
        return TypeAliasDecl(name, generics, target, tok.pos, tok.line, tok.col)

    def parse_type(self):
        """Parse the `type` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value produced by the function, if any.
        """
        typ: str
        if self.opt("*"):
            typ = f"*{type_text(self.parse_type())}"
        elif self.opt("&"):
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
            typ = f"fn({', '.join(args)}) {type_text(self.parse_type())}"
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
        """Parse the `block` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value described by the function return annotation.
        """
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
                self.recover()
        self.eat("}")
        return body

    def parse_global_binding(self) -> LetStmt:
        tok = self.cur()
        if self.cur().kind not in {"let", "fixed"}:
            self._err("expected top-level binding")
            raise ParseError(self.errors[-1])
        is_fixed = self.eat(self.cur().kind).kind == "fixed"
        is_mut = bool(self.opt("mut"))
        if is_mut:
            self._err("top-level bindings cannot be mutable", tok)
            raise ParseError(self.errors[-1])
        name_tok = self.eat("IDENT")
        type_name = None
        if self.opt(":"):
            type_name = self.parse_type()
        self.eat("=")
        expr = self.parse_expr()
        self.eat(";")
        return LetStmt(name_tok.text, expr, False, type_name, tok.pos, tok.line, tok.col, fixed=is_fixed)

    def parse_stmt(self):
        """Parse the `stmt` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value produced by the function, if any.
        """
        tok = self.cur()
        if self.cur().kind == "extern":
            self._err("extern function declarations are only allowed at module scope", tok)
            raise ParseError(self.errors[-1])
        if self.cur().kind == "@":
            self._err("attributes are only allowed on module-level declarations", tok)
            raise ParseError(self.errors[-1])
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
        """Parse the `for` grammar production from the token stream.
        
        Parameters:
            tok: Input value used by this function.
        
        Returns:
            Value described by the function return annotation.
        """
        if self.cur().kind != "IDENT" or self.peek().kind != "in":
            self._err("for expects `for <ident> in <expr> { ... }`")
            raise ParseError(self.errors[-1])
        ident = self.eat("IDENT")
        self.eat("in")
        start_or_iter = self.parse_expr()
        iterable: Any = start_or_iter
        if self.opt(".."):
            dots_tok = self.toks[self.i - 1]
            inclusive = bool(self.opt("="))
            end_expr = self.parse_expr()
            iterable = RangeExpr(start_or_iter, end_expr, inclusive, dots_tok.pos, dots_tok.line, dots_tok.col)
        body = self.parse_block()
        return ForStmt(ident.text, iterable, body, tok.pos, tok.line, tok.col)

    def parse_match(self, tok: Token) -> MatchStmt:
        """Parse the `match` grammar production from the token stream.
        
        Parameters:
            tok: Input value used by this function.
        
        Returns:
            Value described by the function return annotation.
        """
        expr = self.parse_expr()
        self.eat("{")
        arms: list[tuple[Any, list[Any]]] = []
        while self.cur().kind != "}":
            if self.cur().kind == "IDENT" and self.cur().text == "_":
                wtok = self.eat("IDENT")
                pattern = WildcardPattern(wtok.pos, wtok.line, wtok.col)
            else:
                pattern = self.parse_expr()
            self.eat("=>")
            body = self.parse_block()
            arms.append((pattern, body))
            self.opt(",")
        self.eat("}")
        return MatchStmt(expr, arms, tok.pos, tok.line, tok.col)

    def parse_expr(self, min_prec: int = 1):
        """Parse the `expr` grammar production from the token stream.
        
        Parameters:
            min_prec: Input value used by this function.
        
        Returns:
            Value produced by the function, if any.
        """
        left = self.parse_cast()
        while self.cur().kind in BIN_PREC and BIN_PREC[self.cur().kind] >= min_prec:
            op_tok = self.eat(self.cur().kind)
            prec = BIN_PREC[op_tok.kind]
            right = self.parse_expr(prec + 1)
            left = Binary(op_tok.kind, left, right, op_tok.pos, op_tok.line, op_tok.col)
        return left

    def parse_cast(self):
        """Parse the `cast` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value produced by the function, if any.
        """
        expr = self.parse_unary()
        while self.opt("as"):
            tok = self.toks[self.i - 1]
            expr = CastExpr(expr, self.parse_type(), tok.pos, tok.line, tok.col)
        return expr

    def parse_unary(self):
        """Parse the `unary` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value produced by the function, if any.
        """
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
        """Parse the `postfix` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value produced by the function, if any.
        """
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
        """Parse the `atom` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value produced by the function, if any.
        """
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
    """Execute the `Execute the function.` function.
    
    Parameters:
        src: Astra source text to process.
        filename: Filename context used for diagnostics or path resolution.
    
    Returns:
        Value produced by the function, if any.
    """
    return Parser(src, filename=filename).parse_program()
