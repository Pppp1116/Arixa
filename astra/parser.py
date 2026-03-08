"""Recursive-descent parser that turns tokens into AST declarations/statements."""

from __future__ import annotations

from astra.ast import *
from astra.int_types import parse_int_type_name
from astra.lexer import Token, lex
from astra.error_reporting import ErrorReporter, EnhancedError


class ParseError(SyntaxError):
    """Error type raised by the parser subsystem.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    
    def __init__(self, message: str, enhanced_errors: Optional[List[EnhancedError]] = None):
        super().__init__(message)
        self.enhanced_errors = enhanced_errors
    
    def __str__(self) -> str:
        if self.enhanced_errors:
            reporter = ErrorReporter()
            return reporter.format_multiple_errors(self.enhanced_errors)
        return super().__str__()


class EnhancedParser:
    """Enhanced parser with improved error reporting."""
    
    def __init__(self, src: str, filename: str = "<input>"):
        self.filename = filename
        self.src = src
        self.toks = lex(src, filename=filename)
        self.i = 0
        self.errors: List[str] = []
        self.error_reporter = ErrorReporter()
        self.source_lines = src.splitlines()
    
    def create_error(
        self,
        error_type: str,
        message: str,
        line: int,
        col: int,
        severity: str = "error",
        error_code: Optional[str] = None
    ) -> EnhancedError:
        """Create an enhanced parser error."""
        return self.error_reporter.create_enhanced_error(
            error_type=error_type,
            message=message,
            filename=self.filename,
            line=line,
            col=col,
            source_lines=self.source_lines,
            severity=severity,
            error_code=error_code
        )
    
    def _err(self, msg: str, tok: Token | None = None) -> None:
        """Add an error message with enhanced context."""
        t = tok or self.cur()
        error = self.create_error(
            error_type="syntax_error",
            message=msg,
            line=t.line,
            col=t.col,
            error_code="PARSE001"
        )
        self.errors.append(str(error))


BIN_PREC = {
    "??": 1,
    "||": 2,
    "&&": 3,
    "|": 4,
    "^": 5,
    "&": 6,
    "==": 7,
    "!=": 7,
    "is": 7,
    "<": 8,
    "<=": 8,
    ">": 8,
    ">=": 8,
    "..": 8,
    "..=": 8,
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


def _split_top_level_type(text: str, sep: str) -> list[str]:
    out: list[str] = []
    depth_angle = 0
    depth_paren = 0
    depth_bracket = 0
    cur: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "<":
            depth_angle += 1
        elif ch == ">" and depth_angle > 0:
            depth_angle -= 1
        elif ch == "(":
            depth_paren += 1
        elif ch == ")" and depth_paren > 0:
            depth_paren -= 1
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]" and depth_bracket > 0:
            depth_bracket -= 1
        if (
            text.startswith(sep, i)
            and depth_angle == 0
            and depth_paren == 0
            and depth_bracket == 0
        ):
            out.append("".join(cur).strip())
            cur = []
            i += len(sep)
            continue
        cur.append(ch)
        i += 1
    out.append("".join(cur).strip())
    return out


def _normalize_union(parts: list[str]) -> str:
    flat: list[str] = []
    for p in parts:
        for sub in _split_top_level_type(type_text(p), "|"):
            t = sub.strip()
            if t:
                flat.append(t)
    out: list[str] = []
    seen: set[str] = set()
    for t in flat:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return " | ".join(out)


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
            n: Input value used by this routine.
        
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
            kind: Input value used by this routine.
        
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
            kind: Input value used by this routine.
        
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

    def _looks_like_binding_start(self, idx: int | None = None) -> bool:
        j = self.i if idx is None else idx
        if self.toks[j].kind == "mut":
            j += 1
        if self.toks[j].kind != "IDENT":
            return False
        j += 1
        if self.toks[j].kind == ":":
            j += 1
            depth_angle = 0
            depth_paren = 0
            depth_bracket = 0
            while j < len(self.toks):
                k = self.toks[j].kind
                if k == "<":
                    depth_angle += 1
                elif k == ">" and depth_angle > 0:
                    depth_angle -= 1
                elif k == "(":
                    depth_paren += 1
                elif k == ")" and depth_paren > 0:
                    depth_paren -= 1
                elif k == "[":
                    depth_bracket += 1
                elif k == "]" and depth_bracket > 0:
                    depth_bracket -= 1
                elif k == "=" and depth_angle == 0 and depth_paren == 0 and depth_bracket == 0:
                    return True
                elif k in {";", "}", "EOF"} and depth_angle == 0 and depth_paren == 0 and depth_bracket == 0:
                    return False
                j += 1
            return False
        return self.toks[j].kind == "="

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
            "trait",
            "type",
            "import",
            "extern",
            "mut",
            "set",
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
            doc: Input value used by this routine.
        
        Returns:
            Value produced by the routine, if any.
        """
        is_pub = False
        is_unsafe = False
        is_async = False
        is_gpu = False
        is_packed = False
        derives: list[str] = []
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
            if self.cur().kind == "IDENT" and self.cur().text == "gpu" and self.peek().kind == "fn":
                self.i += 1
                is_gpu = True
                continue
            if self.opt("@"):
                attr = self.eat("IDENT").text
                if attr == "packed":
                    is_packed = True
                    continue
                if attr == "derive":
                    self.eat("(")
                    if self.cur().kind != "IDENT":
                        self._err("@derive expects at least one identifier, for example @derive(Serialize)")
                        raise ParseError(self.errors[-1])
                    derives.append(self.eat("IDENT").text)
                    while self.opt(","):
                        derives.append(self.eat("IDENT").text)
                    self.eat(")")
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
            if derives:
                self._err("@derive is only valid on struct/enum declarations")
                raise ParseError(self.errors[-1])
            if is_unsafe or is_async or is_gpu:
                self._err("import cannot be prefixed with unsafe/async/gpu")
                raise ParseError(self.errors[-1])
            if is_packed:
                self._err("@packed is only valid on struct declarations")
                raise ParseError(self.errors[-1])
            return self.parse_import()
        if self.cur().kind == "struct":
            if link_libs:
                self._err("@link is only valid on extern function declarations")
                raise ParseError(self.errors[-1])
            if is_unsafe or is_async or is_gpu:
                self._err("struct cannot be prefixed with unsafe/async/gpu")
                raise ParseError(self.errors[-1])
            return self.parse_struct(is_pub, doc, packed=is_packed, derives=derives)
        if self.cur().kind == "enum":
            if link_libs:
                self._err("@link is only valid on extern function declarations")
                raise ParseError(self.errors[-1])
            if is_unsafe or is_async or is_gpu:
                self._err("enum cannot be prefixed with unsafe/async/gpu")
                raise ParseError(self.errors[-1])
            if is_packed:
                self._err("@packed is only valid on struct declarations")
                raise ParseError(self.errors[-1])
            return self.parse_enum(is_pub, doc, derives=derives)
        if self.cur().kind == "trait":
            if link_libs:
                self._err("@link is only valid on extern function declarations")
                raise ParseError(self.errors[-1])
            if is_unsafe or is_async or is_gpu:
                self._err("trait cannot be prefixed with unsafe/async/gpu")
                raise ParseError(self.errors[-1])
            if is_packed:
                self._err("@packed is only valid on struct declarations")
                raise ParseError(self.errors[-1])
            if derives:
                self._err("@derive is only valid on struct/enum declarations")
                raise ParseError(self.errors[-1])
            return self.parse_trait(is_pub, doc)
        if self.cur().kind == "type":
            if link_libs:
                self._err("@link is only valid on extern function declarations")
                raise ParseError(self.errors[-1])
            if is_unsafe or is_async or is_gpu:
                self._err("type alias cannot be prefixed with unsafe/async/gpu")
                raise ParseError(self.errors[-1])
            if is_packed:
                self._err("@packed is only valid on struct declarations")
                raise ParseError(self.errors[-1])
            if derives:
                self._err("@derive is only valid on struct/enum declarations")
                raise ParseError(self.errors[-1])
            return self.parse_type_alias()
        if self.cur().kind == "const":
            if link_libs:
                self._err("@link is only valid on extern function declarations")
                raise ParseError(self.errors[-1])
            if is_unsafe or is_async or is_gpu:
                self._err("const cannot be prefixed with unsafe/async/gpu")
                raise ParseError(self.errors[-1])
            if is_packed:
                self._err("@packed is only valid on struct declarations")
                raise ParseError(self.errors[-1])
            if derives:
                self._err("@derive is only valid on struct/enum declarations")
                raise ParseError(self.errors[-1])
            return self.parse_const(is_pub, doc)
        if self.cur().kind == "extern":
            if is_gpu:
                self._err("extern functions cannot be prefixed with gpu")
                raise ParseError(self.errors[-1])
            if is_packed:
                self._err("@packed is only valid on struct declarations")
                raise ParseError(self.errors[-1])
            if derives:
                self._err("@derive is only valid on struct/enum declarations")
                raise ParseError(self.errors[-1])
            return self.parse_extern_fn(is_pub, is_unsafe, doc, link_libs=link_libs)
        if self.cur().kind == "fn":
            if is_packed:
                self._err("@packed is only valid on struct declarations")
                raise ParseError(self.errors[-1])
            if link_libs:
                self._err("@link is only valid on extern function declarations")
                raise ParseError(self.errors[-1])
            if derives:
                self._err("@derive is only valid on struct/enum declarations")
                raise ParseError(self.errors[-1])
            return self.parse_fn(is_pub, is_async, doc, is_unsafe=is_unsafe, is_gpu=is_gpu)
        if self._looks_like_binding_start():
            if link_libs or is_packed or is_pub or is_async or is_gpu or derives:
                self._err("top-level bindings cannot use declaration modifiers or attributes")
                raise ParseError(self.errors[-1])
            return self.parse_global_binding(is_unsafe=is_unsafe)
        if is_gpu:
            self._err("gpu modifier is only valid before fn declarations")
            raise ParseError(self.errors[-1])
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

    def _parse_generics(self) -> tuple[list[str], list[tuple[str, str]]]:
        generics: list[str] = []
        bounds: list[tuple[str, str]] = []
        if self.cur().kind != "<":
            return generics, bounds
        if self.peek().kind != "IDENT":
            return generics, bounds
        self.eat("<")
        while True:
            tvar = self.eat("IDENT").text
            generics.append(tvar)
            # Accept both `<T Trait>` and `<T: Trait>` while normalizing formatter output.
            if self.opt(":") or self.cur().kind == "IDENT":
                if self.cur().kind == "IDENT":
                    bounds.append((tvar, self.eat("IDENT").text))
                    while self.opt("+"):
                        bounds.append((tvar, self.eat("IDENT").text))
            if not self.opt(","):
                break
        self.eat(">")
        return generics, bounds

    def _parse_where_bounds(self) -> list[tuple[str, str]]:
        bounds: list[tuple[str, str]] = []
        if not self.opt("where"):
            return bounds
        while True:
            tvar = self.eat("IDENT").text
            self.eat(":")
            bounds.append((tvar, self.eat("IDENT").text))
            while self.opt("+"):
                bounds.append((tvar, self.eat("IDENT").text))
            if not self.opt(","):
                break
        return bounds

    def _parse_params(self, *, allow_variadic: bool = False) -> tuple[list[tuple[str, str]], bool, dict[str, bool]]:
        params: list[tuple[str, str]] = []
        param_mut: dict[str, bool] = {}
        variadic = False
        self.eat("(")
        if self.cur().kind != ")":
            if allow_variadic and self.cur().kind == "...":
                self.eat("...")
                variadic = True
            else:
                name, typ, is_mut = self._parse_param_type()
                params.append((name, typ))
                param_mut[name] = is_mut
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
                name, typ, is_mut = self._parse_param_type()
                params.append((name, typ))
                param_mut[name] = is_mut
            if variadic and self.cur().kind != ")":
                self._err("variadic marker `...` must be the last parameter")
                raise ParseError(self.errors[-1])
        self.eat(")")
        return params, variadic, param_mut

    def _parse_named_type(self) -> tuple[str, str]:
        name = self.eat("IDENT").text
        self.opt(":")
        typ = self.parse_type()
        return name, typ

    def _parse_param_type(self) -> tuple[str, str, bool]:
        is_mut = bool(self.opt("mut"))
        name = self.eat("IDENT").text
        self.opt(":")  # Consume optional colon
        typ = self.parse_type()
        return name, typ, is_mut

    def _starts_type(self) -> bool:
        return self.cur().kind in {"IDENT", "INT_TYPE", "ARBITRARY_INT_TYPE", "none", "*", "&", "[", "fn", "f16", "f80", "f128"}

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
            is_pub: Input value used by this routine.
            is_unsafe: Input value used by this routine.
            doc: Input value used by this routine.
        
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
        params, is_variadic, param_mut = self._parse_params(allow_variadic=True)
        if self.opt("->"):
            self._err("`->` is no longer valid in function signatures; place return type after `)`")
            raise ParseError(self.errors[-1])
        ret = self.parse_type() if self._starts_type() else "Void"
        self.eat(";")
        out = ExternFnDecl(
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
        setattr(out, "param_mut", param_mut)
        return out

    def parse_fn(
        self,
        is_pub: bool = False,
        is_async: bool = False,
        doc: str = "",
        is_unsafe: bool = False,
        is_gpu: bool = False,
    ) -> FnDecl:
        """Parse the `fn` grammar production from the token stream.
        
        Parameters:
            is_pub: Input value used by this routine.
            is_async: Input value used by this routine.
            doc: Input value used by this routine.
            is_unsafe: Input value used by this routine.
        
        Returns:
            Value described by the function return annotation.
        """
        fn_tok = self.eat("fn")
        name = self.eat("IDENT").text
        generics, inline_bounds = self._parse_generics()
        params, _, param_mut = self._parse_params()
        if self.opt("->"):
            self._err("`->` is no longer valid in function signatures; place return type after `)`")
            raise ParseError(self.errors[-1])
        ret = self.parse_type() if self._starts_type() else "Void"
        where_bounds = inline_bounds + self._parse_where_bounds()
        body = self.parse_block()
        if ret != "Void":
            body = self._rewrite_implicit_tail_return(body)
        out = FnDecl(
            name,
            generics,
            params,
            ret,
            body,
            pub=is_pub,
            async_fn=is_async,
            unsafe=is_unsafe,
            doc=doc,
            where_bounds=where_bounds,
            gpu_kernel=is_gpu,
            pos=fn_tok.pos,
            line=fn_tok.line,
            col=fn_tok.col,
        )
        setattr(out, "param_mut", param_mut)
        return out

    def parse_struct(self, is_pub: bool = False, doc: str = "", packed: bool = False, derives: list[str] | None = None) -> StructDecl:
        """Parse the `struct` grammar production from the token stream.
        
        Parameters:
            is_pub: Input value used by this routine.
            doc: Input value used by this routine.
            packed: Input value used by this routine.
        
        Returns:
            Value described by the function return annotation.
        """
        tok = self.eat("struct")
        name = self.eat("IDENT").text
        generics, bounds = self._parse_generics()
        if bounds:
            self._err("struct generics do not support trait bounds")
            raise ParseError(self.errors[-1])
        self.eat("{")
        fields: list[tuple[str, str]] = []
        while self.cur().kind != "}":
            fields.append(self._parse_named_type())
            self.opt(",")
        self.eat("}")
        return StructDecl(name, generics, fields, [], derives=list(derives or []), pub=is_pub, packed=packed, doc=doc, pos=tok.pos, line=tok.line, col=tok.col)

    def parse_enum(self, is_pub: bool = False, doc: str = "", derives: list[str] | None = None) -> EnumDecl:
        """Parse the `enum` grammar production from the token stream.
        
        Parameters:
            is_pub: Input value used by this routine.
            doc: Input value used by this routine.
        
        Returns:
            Value described by the function return annotation.
        """
        tok = self.eat("enum")
        name = self.eat("IDENT").text
        generics, bounds = self._parse_generics()
        if bounds:
            self._err("enum generics do not support trait bounds")
            raise ParseError(self.errors[-1])
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
        return EnumDecl(name, generics, variants, derives=list(derives or []), pub=is_pub, doc=doc, pos=tok.pos, line=tok.line, col=tok.col)

    def parse_type_alias(self) -> TypeAliasDecl:
        """Parse the `type_alias` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value described by the function return annotation.
        """
        tok = self.eat("type")
        name = self.eat("IDENT").text
        generics, bounds = self._parse_generics()
        if bounds:
            self._err("type alias generics do not support trait bounds")
            raise ParseError(self.errors[-1])
        self.eat("=")
        target = self.parse_type()
        self.opt(";")
        return TypeAliasDecl(name, generics, target, tok.pos, tok.line, tok.col)

    def parse_const(self, is_pub: bool = False, doc: str = "") -> ConstDecl:
        """Parse the `const` grammar production from the token stream.
        
        Parameters:
            is_pub: Input value used by this routine.
            doc: Input value used by this routine.
        
        Returns:
            Value described by the function return annotation.
        """
        tok = self.eat("const")
        name = self.eat("IDENT").text
        self.eat("=")
        expr = self.parse_expr()
        self.opt(";")
        return ConstDecl(name, expr, is_pub, doc, tok.pos, tok.line, tok.col)

    def parse_trait(self, is_pub: bool = False, doc: str = "") -> TraitDecl:
        tok = self.eat("trait")
        name = self.eat("IDENT").text
        self.eat("{")
        methods: list[tuple[str, list[tuple[str, str]], str]] = []
        while self.cur().kind != "}":
            self.eat("fn")
            mname = self.eat("IDENT").text
            _, _ = self._parse_generics()
            params, _, _ = self._parse_params()
            if self.opt("->"):
                self._err("`->` is no longer valid in function signatures; place return type after `)`")
                raise ParseError(self.errors[-1])
            ret = self.parse_type() if self._starts_type() else "Void"
            self.eat(";")
            methods.append((mname, params, ret))
        self.eat("}")
        return TraitDecl(name, methods, pub=is_pub, doc=doc, pos=tok.pos, line=tok.line, col=tok.col)

    def parse_type(self):
        """Parse the `type` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value produced by the routine, if any.
        """
        def parse_atom_type():
            typ: str
            if self.opt("*"):
                typ = f"*{type_text(parse_atom_type())}"
            elif self.opt("&"):
                mut = "mut " if self.opt("mut") else ""
                typ = f"&{mut}{type_text(parse_atom_type())}"
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
                if self.cur().kind in {"IDENT", "ARBITRARY_INT_TYPE", "INT_TYPE", "none", "f16", "f80", "f128"}:
                    tok_kind = self.cur().kind
                    name = self.eat(tok_kind).text
                    if tok_kind == "ARBITRARY_INT_TYPE":
                        # Handle arbitrary precision integer types like i123, u456
                        int_info = parse_int_type_name(name)
                        if int_info is not None:
                            bits, signed = int_info
                            typ = str(ArbitraryIntType(signed=signed, width=bits))
                        else:
                            self._err(f"invalid arbitrary precision integer type: {name}")
                            raise ParseError(self.errors[-1])
                    elif tok_kind == "INT_TYPE":
                        # Handle built-in integer types
                        typ = name
                    elif tok_kind in {"f16", "f80", "f128"}:
                        typ = name
                    else:
                        int_info = parse_int_type_name(name)
                        if int_info is not None:
                            bits, signed = int_info
                            # Don't convert Int, isize, usize to ArbitraryIntType
                            if name in {"Int", "isize", "usize"}:
                                typ = name
                            else:
                                typ = str(ArbitraryIntType(signed=signed, width=bits))
                        else:
                            typ = name
                else:
                    self._err(f"expected type, got {self.cur().kind}")
                    raise ParseError(self.errors[-1])
            return typ
        
        parts = [type_text(parse_atom_type())]
        while self.opt("|"):
            parts.append(type_text(parse_atom_type()))
        return _normalize_union(parts)

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

    def parse_global_binding(self, *, is_unsafe: bool = False) -> LetStmt:
        tok = self.cur()
        is_mut = bool(self.opt("mut"))
        if is_mut and not is_unsafe:
            self._err("top-level mutable bindings require `unsafe mut`", tok)
            raise ParseError(self.errors[-1])
        name_tok = self.eat("IDENT")
        type_name = None
        if self.opt(":"):
            type_name = self.parse_type()
        self.eat("=")
        expr = self.parse_expr()
        self.eat(";")
        out = LetStmt(name_tok.text, expr, is_mut, type_name, tok.pos, tok.line, tok.col, reassign_if_exists=False)
        setattr(out, "_decl_unsafe", bool(is_unsafe))
        return out

    def _parse_binding_stmt(self, tok: Token, *, starts_with_mut: bool, reassign_if_exists: bool) -> LetStmt:
        is_mut = starts_with_mut or bool(self.opt("mut"))
        name_tok = self.eat("IDENT")
        type_name = None
        if self.opt(":"):
            type_name = self.parse_type()
        self.eat("=")
        expr = self.parse_expr()
        self.eat(";")
        return LetStmt(
            name_tok.text,
            expr,
            is_mut,
            type_name,
            tok.pos,
            tok.line,
            tok.col,
            reassign_if_exists=reassign_if_exists,
        )

    def parse_stmt(self, allow_no_semicolon: bool = False):
        """Parse the `stmt` grammar production from the token stream.
        
        Parameters:
            allow_no_semicolon: If True, don't require a trailing semicolon
        
        Returns:
            Value produced by the routine, if any.
        """
        tok = self.cur()
        if self.cur().kind == "extern":
            self._err("extern function declarations are only allowed at module scope", tok)
            raise ParseError(self.errors[-1])
        if self.cur().kind == "@":
            self._err("attributes are only allowed on module-level declarations", tok)
            raise ParseError(self.errors[-1])
        if self.cur().kind == "mut" and self._looks_like_binding_start():
            self.eat("mut")
            return self._parse_binding_stmt(tok, starts_with_mut=True, reassign_if_exists=False)
        if self.cur().kind == "IDENT" and self._looks_like_binding_start():
            return self._parse_binding_stmt(tok, starts_with_mut=False, reassign_if_exists=True)
        if self.opt("return"):
            if self.opt(";"):
                return ReturnStmt(None, tok.pos, tok.line, tok.col)
            else:
                e = self.parse_expr()
                if not allow_no_semicolon:
                    self.eat(";")
                return ReturnStmt(e, tok.pos, tok.line, tok.col)
        if self.opt("break"):
            if not allow_no_semicolon:
                self.eat(";")
            return BreakStmt(tok.pos, tok.line, tok.col)
        if self.opt("continue"):
            if not allow_no_semicolon:
                self.eat(";")
            return ContinueStmt(tok.pos, tok.line, tok.col)
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
            # Check for enhanced while loop with inline mutable variable
            if self.opt("mut"):
                if self.cur().kind == "IDENT":
                    var_name = self.eat("IDENT").text
                    condition = self.parse_expr()
                    body = self.parse_block()
                    # Create LetStmt for binding
                    var_decl = LetStmt(var_name, None, True, None, tok.pos, tok.line, tok.col)
                    return EnhancedWhileStmt(var_decl, condition, body, tok.pos, tok.line, tok.col)
                else:
                    self._err("expected identifier after 'mut' in while condition")
                    raise ParseError(self.errors[-1])
            else:
                # Regular while loop
                cond = self.parse_expr()
                body = self.parse_block()
                return WhileStmt(cond, body, tok.pos, tok.line, tok.col)
        if self.opt("for"):
            # Iterator-style for loop only
            return self.parse_for(tok)
        if self.opt("match"):
            return self.parse_match(tok)
        if self.opt("unsafe"):
            body = self.parse_block()
            return UnsafeStmt(body, tok.pos, tok.line, tok.col)

        explicit_set = bool(self.opt("set"))
        lhs = self.parse_expr()
        if self.cur().kind in ASSIGN_OPS:
            op = self.eat(self.cur().kind).kind
            expr = self.parse_expr()
            self.eat(";")
            return AssignStmt(lhs, op, expr, tok.pos, tok.line, tok.col, explicit_set=explicit_set)
        if explicit_set:
            self._err("expected assignment operator after `set`", tok)
            raise ParseError(self.errors[-1])
        if self.cur().kind == ";":
            self.eat(";")
        elif allow_no_semicolon and self.cur().kind == ",":
            # Allow comma as terminator for match arms
            pass
        elif self.cur().kind != "}":
            self._err("expected `;`", self.cur())
            raise ParseError(self.errors[-1])
        return ExprStmt(lhs, tok.pos, tok.line, tok.col)

    def _rewrite_implicit_tail_return(self, body: list[Any]) -> list[Any]:
        if not body:
            return body
        tail = body[-1]
        if isinstance(tail, ExprStmt):
            return body[:-1] + [ReturnStmt(tail.expr, tail.pos, tail.line, tail.col)]
        if isinstance(tail, IfStmt):
            if not tail.then_body or not tail.else_body:
                return body
            then_body = self._rewrite_implicit_tail_return(tail.then_body)
            else_body = self._rewrite_implicit_tail_return(tail.else_body)
            new_tail = IfStmt(tail.cond, then_body, else_body, tail.pos, tail.line, tail.col)
            return body[:-1] + [new_tail]
        if isinstance(tail, MatchStmt):
            new_arms: list[tuple[Any, list[Any]]] = []
            for pat, arm in tail.arms:
                if not arm:
                    return body
                # Handle both single statements and blocks
                if isinstance(arm, list):
                    new_arm = self._rewrite_implicit_tail_return(arm)
                else:
                    # Single statement - wrap in list to normalize
                    new_arm = self._rewrite_implicit_tail_return([arm])
                new_arms.append((pat, new_arm))
            new_tail = MatchStmt(tail.expr, new_arms, tail.pos, tail.line, tail.col)
            return body[:-1] + [new_tail]
        if isinstance(tail, UnsafeStmt):
            new_tail = UnsafeStmt(self._rewrite_implicit_tail_return(tail.body), tail.pos, tail.line, tail.col)
            return body[:-1] + [new_tail]
        return body

    def parse_for(self, tok: Token) -> IteratorForStmt:
        """Parse the `for` grammar production from the token stream.
        
        Parameters:
            tok: Input value used by this routine.
        
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
        return IteratorForStmt(ident.text, iterable, body, tok.pos, tok.line, tok.col)

    def parse_match(self, tok: Token) -> MatchStmt:
        """Parse the `match` grammar production from the token stream.
        
        Parameters:
            tok: Input value used by this routine.
        
        Returns:
            Value described by the function return annotation.
        """
        expr = self.parse_expr()
        self.eat("{")
        arms: list[tuple[Any, Any]] = []
        while self.cur().kind != "}":
            pattern = self.parse_match_pattern()
            self.eat("=>")
            # Check if it's a block or statement
            if self.cur().kind == "{":
                # Block arm
                body = self.parse_block()
                self.opt(",")
                arms.append((pattern, body))
            else:
                # Statement arm (like return, break, etc.)
                # Parse statement without requiring semicolon for match arms
                stmt = self._parse_match_arm_stmt()
                # Normalize to list for consistent handling
                if not isinstance(stmt, list):
                    stmt = [stmt]
                self.opt(",")
                arms.append((pattern, stmt))
        self.eat("}")
        return MatchStmt(expr, arms, tok.pos, tok.line, tok.col)

    def _parse_match_arm_stmt(self):
        """Parse a statement within a match arm, without requiring semicolon."""
        if self.cur().kind == "return":
            tok = self.eat("return")
            if self.cur().kind == "," or self.cur().kind == "}":
                # Empty return
                return ReturnStmt(None, tok.pos, tok.line, tok.col)
            else:
                # Return with expression
                e = self.parse_expr()
                return ReturnStmt(e, tok.pos, tok.line, tok.col)
        if self.cur().kind == "break":
            tok = self.eat("break")
            return BreakStmt(tok.pos, tok.line, tok.col)
        if self.cur().kind == "continue":
            tok = self.eat("continue")
            return ContinueStmt(tok.pos, tok.line, tok.col)
        # For other statements, fall back to regular parsing with semicolon-optional
        stmt = self.parse_stmt(allow_no_semicolon=True)
        return stmt

    def parse_match_pattern(self):
        """Parse one match arm pattern, including `|` alternatives and optional guard."""
        first = self.parse_match_pattern_atom()
        patterns = [first]
        while self.opt("|"):
            patterns.append(self.parse_match_pattern_atom())
        pattern: Any = patterns[0]
        if len(patterns) > 1:
            pattern = OrPattern(patterns, first.pos, first.line, first.col)
        if self.opt("if"):
            if_tok = self.toks[self.i - 1]
            guard = self.parse_expr()
            pattern = GuardedPattern(pattern, guard, if_tok.pos, if_tok.line, if_tok.col)
        return pattern

    def parse_match_pattern_atom(self):
        """Parse one pattern alternative inside a match arm."""
        if self.cur().kind == "IDENT" and self.cur().text == "_":
            wtok = self.eat("IDENT")
            return WildcardPattern(wtok.pos, wtok.line, wtok.col)
        
        # Parse literal patterns
        if self.cur().kind in ("INT_LIT", "FLOAT_LIT", "STR_LIT", "TRUE", "FALSE"):
            return self.parse_literal_pattern()
        
        # Parse range patterns
        if self.cur().kind == "IDENT" and self.peek().kind == "..":
            return self.parse_range_pattern()
        
        # Parse slice patterns
        if self.cur().kind == "[":
            return self.parse_slice_pattern()
        
        # Parse tuple patterns
        if self.cur().kind == "(":
            return self.parse_tuple_pattern()
        
        # Parse struct patterns
        if self.cur().kind == "IDENT" and self.peek().kind == "{":
            return self.parse_struct_pattern()
        
        # Keep `|` available for match-pattern alternatives.
        return self.parse_expr(5)

    def parse_literal_pattern(self):
        """Parse literal patterns like 42, "hello", true."""
        if self.cur().kind == "INT_LIT":
            tok = self.eat("INT_LIT")
            return LiteralPattern(IntLit(tok.text, tok.pos, tok.line, tok.col), tok.pos, tok.line, tok.col)
        elif self.cur().kind == "FLOAT_LIT":
            tok = self.eat("FLOAT_LIT")
            return LiteralPattern(FloatLit(tok.text, tok.pos, tok.line, tok.col), tok.pos, tok.line, tok.col)
        elif self.cur().kind == "STR_LIT":
            tok = self.eat("STR_LIT")
            return LiteralPattern(StringLit(tok.text, tok.pos, tok.line, tok.col), tok.pos, tok.line, tok.col)
        elif self.cur().kind == "TRUE":
            tok = self.eat("TRUE")
            return LiteralPattern(BoolLit(True, tok.pos, tok.line, tok.col), tok.pos, tok.line, tok.col)
        elif self.cur().kind == "FALSE":
            tok = self.eat("FALSE")
            return LiteralPattern(BoolLit(False, tok.pos, tok.line, tok.col), tok.pos, tok.line, tok.col)
        else:
            self._err("expected literal pattern", self.cur())
            raise ParseError(self.errors[-1])

    def parse_range_pattern(self):
        """Parse range patterns like 1..10 or 1..=10."""
        start_tok = self.eat("IDENT")  # This should be an expression, simplified for now
        dots_tok = self.eat("..")
        inclusive = bool(self.opt("="))
        end_tok = self.eat("IDENT")  # This should be an expression, simplified for now
        
        return RangePattern(
            start_tok, end_tok, inclusive, 
            start_tok.pos, start_tok.line, start_tok.col
        )

    def parse_slice_pattern(self):
        """Parse slice patterns like [a, b, ..]."""
        lbrack = self.eat("[")
        patterns = []
        rest_pattern = None
        
        while self.cur().kind != "]":
            if self.cur().kind == "..":
                rest_pattern = WildcardPattern(self.cur().pos, self.cur().line, self.cur().col)
                self.eat("..")
                break
            else:
                patterns.append(self.parse_match_pattern_atom())
                if not self.opt(","):
                    break
        
        self.eat("]")
        return SlicePattern(patterns, rest_pattern, lbrack.pos, lbrack.line, lbrack.col)

    def parse_tuple_pattern(self):
        """Parse tuple patterns like (a, b, c)."""
        lparen = self.eat("(")
        patterns = []
        
        if self.cur().kind != ")":
            patterns.append(self.parse_match_pattern_atom())
            while self.opt(","):
                if self.cur().kind == ")":
                    break
                patterns.append(self.parse_match_pattern_atom())
        
        self.eat(")")
        return TuplePattern(patterns, lparen.pos, lparen.line, lparen.col)

    def parse_struct_pattern(self):
        """Parse struct patterns like Point { x, y }."""
        struct_name_tok = self.eat("IDENT")
        self.eat("{")
        
        field_patterns = {}
        
        if self.cur().kind != "}":
            while True:
                field_name = self.eat("IDENT").text
                if self.opt(":"):
                    pattern = self.parse_match_pattern_atom()
                    field_patterns[field_name] = pattern
                else:
                    # Shorthand: Point { x, y } means Point { x: x, y: y }
                    field_patterns[field_name] = Name(field_name, 0, 0, 0)
                
                if not self.opt(","):
                    break
        
        self.eat("}")
        return StructPattern(struct_name_tok.text, field_patterns, struct_name_tok.pos, struct_name_tok.line, struct_name_tok.col)

    def parse_expr(self, min_prec: int = 1):
        """Parse the `expr` grammar production from the token stream.
        
        Parameters:
            min_prec: Input value used by this routine.
        
        Returns:
            Value produced by the routine, if any.
        """
        left = self.parse_cast()
        while self.cur().kind in BIN_PREC and BIN_PREC[self.cur().kind] >= min_prec:
            op_tok = self.eat(self.cur().kind)
            prec = BIN_PREC[op_tok.kind]
            
            # Handle range expressions specially
            if op_tok.kind in ("..", "..="):
                right = self.parse_expr(prec + 1)
                inclusive = op_tok.kind == "..="
                left = RangeExpr(left, right, inclusive, op_tok.pos, op_tok.line, op_tok.col)
            elif op_tok.kind == "is":
                right = Name(self.parse_type(), op_tok.pos, op_tok.line, op_tok.col)
                left = Binary(op_tok.kind, left, right, op_tok.pos, op_tok.line, op_tok.col)
            else:
                right = self.parse_expr(prec + 1)
                left = Binary(op_tok.kind, left, right, op_tok.pos, op_tok.line, op_tok.col)
        return left

    def parse_cast(self):
        """Parse the `cast` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value produced by the routine, if any.
        """
        expr = self.parse_unary()
        while self.opt("as"):
            tok = self.toks[self.i - 1]
            expr = CastExpr(expr, self.parse_type(), tok.pos, tok.line, tok.col)
        
        # Check for if expression (return if condition { true } else { false })
        if self.cur().kind == "if" and self.i + 1 < len(self.toks) and self.toks[self.i + 1].kind == "{":
            self.eat("if")
            return self.parse_if_expression(expr)
        
        return expr

    def parse_unary(self):
        """Parse the `unary` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value produced by the routine, if any.
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
            Value produced by the routine, if any.
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
            if self.opt("!"):
                q = self.toks[self.i - 1]
                expr = TryExpr(expr, q.pos, q.line, q.col)
                continue
            break
        return expr

    def parse_atom(self):
        """Parse the `atom` grammar production from the token stream.
        
        Parameters:
            none
        
        Returns:
            Value produced by the routine, if any.
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
        if self.opt("TYPED_INT"):
            # Handle typed integer literals like 123i64, 456u32
            text = tok.text
            # Extract the value and type
            # Find where the type suffix starts (i or u)
            suffix_start = -1
            for i, ch in enumerate(text):
                if ch in {"i", "u"} and i + 1 < len(text) and text[i + 1].isdigit():
                    suffix_start = i
                    break
            
            if suffix_start == -1:
                self._err(f"invalid typed integer literal: {text}")
                raise ParseError(self.errors[-1])
            
            value_str = text[:suffix_start]
            type_suffix = text[suffix_start:]
            
            # Parse the integer value
            value = _parse_int_literal(value_str)
            lit = Literal(value, tok.pos, tok.line, tok.col)
            
            # Convert type suffix to actual type name
            if type_suffix.startswith("i"):
                type_name = f"i{type_suffix[1:]}"
            else:  # u prefix
                type_name = f"u{type_suffix[1:]}"
            
            return CastExpr(lit, type_name, tok.pos, tok.line, tok.col)
        if self.opt("FLOAT"):
            return Literal(_parse_float_literal(tok.text), tok.pos, tok.line, tok.col)
        if self.opt("STR"):
            return Literal(tok.text, tok.pos, tok.line, tok.col)
        if self.opt("STR_INTERP"):
            return self.parse_string_interpolation(tok)
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
            
            # Create name expression and check for method calls
            name_expr = Name(tok.text, tok.pos, tok.line, tok.col)
            return self.parse_method_call(name_expr)
        # Check for if expression at the start of an expression
        if self.opt("if"):
            cond = self.parse_expr()
            return self.parse_if_expression(cond)
        
        # Check for collection literals first
        collection_lit = self.parse_collection_literal()
        if collection_lit is not None:
            return collection_lit
        
        if self.opt("("):
            e = self.parse_expr()
            self.eat(")")
            return e
        self._err(f"unexpected atom {self.cur().kind}")
        raise ParseError(self.errors[-1])

    def parse_method_call(self, obj_expr: Any) -> Any:
        """Parse method call syntax like obj.method(args) or field access like obj.field."""
        if self.opt("."):
            if self.cur().kind == "IDENT":
                method_name = self.eat("IDENT").text
                args = []
                if self.opt("("):
                    # This is a method call with arguments
                    while self.cur().kind != ")":
                        args.append(self.parse_expr())
                        if not self.opt(","):
                            break
                    self.eat(")")
                    return MethodCall(obj_expr, method_name, args, obj_expr.pos, obj_expr.line, obj_expr.col)
                else:
                    # This is a field access (for enum variants, struct fields, etc.)
                    return FieldExpr(obj_expr, method_name, obj_expr.pos, obj_expr.line, obj_expr.col)
            else:
                self._err("expected method name after '.'")
                raise ParseError(self.errors[-1])
        return obj_expr

    def parse_collection_literal(self) -> Any:
        """Parse collection literals like [1, 2, 3] or {k: v}."""
        if self.opt("["):
            elements = []
            if self.cur().kind != "]":
                elements.append(self.parse_expr())
                while self.opt(","):
                    elements.append(self.parse_expr())
            end = self.eat("]")
            return VectorLiteral(elements, end.pos, end.line, end.col)
        
        elif self.opt("{"):
            # Check if this is a map literal (has key: value pairs)
            if self.cur().kind != "}" and self._looks_like_map_pair():
                # Map literal
                pairs = []
                if self.cur().kind != "}":
                    key = self.parse_expr()
                    self.eat(":")
                    value = self.parse_expr()
                    pairs.append((key, value))
                    while self.opt(","):
                        key = self.parse_expr()
                        self.eat(":")
                        value = self.parse_expr()
                        pairs.append((key, value))
                end = self.eat("}")
                return MapLiteral(pairs, end.pos, end.line, end.col)
            else:
                # Set literal
                elements = []
                if self.cur().kind != "}":
                    elements.append(self.parse_expr())
                    while self.opt(","):
                        elements.append(self.parse_expr())
                end = self.eat("}")
                return SetLiteral(elements, end.pos, end.line, end.col)
        
        return None
    
    def _looks_like_map_pair(self) -> bool:
        """Check if the current position looks like the start of a map key: value pair."""
        # Save current position
        saved_i = self.i
        
        # Try to parse an expression
        try:
            key_expr = self.parse_expr()
            if self.cur().kind == ":":
                self.i = saved_i  # Restore position
                return True
        except:
            pass
        
        # Restore position
        self.i = saved_i
        return False

    def parse_struct_literal(self, struct_name: str) -> Any:
        """Parse struct literal with positional arguments."""
        if self.opt("("):
            args = []
            if self.cur().kind != ")":
                args.append(self.parse_expr())
                while self.opt(","):
                    args.append(self.parse_expr())
            end = self.eat(")")
            return StructLiteral(struct_name, args, end.pos, end.line, end.col)
        else:
            # Fall back to existing field-based parsing
            return None

    def parse_destructuring_pattern(self) -> Any:
        """Parse destructuring patterns like Point { x, y }."""
        if self.cur().kind == "IDENT" and self.peek().kind == "{":
            struct_name = self.eat("IDENT").text
            self.eat("{")
            fields = []
            while self.cur().kind != "}":
                if self.cur().kind == "IDENT":
                    field_name = self.eat("IDENT").text
                    if self.opt(":"):
                        # Field binding with different name
                        bind_name = self.eat("IDENT").text
                        fields.append((field_name, bind_name))
                    else:
                        # Field binding with same name
                        fields.append((field_name, field_name))
                    self.opt(",")
                else:
                    self._err("expected field name in destructuring pattern")
                    raise ParseError(self.errors[-1])
            self.eat("}")
            return DestructuringPattern(struct_name, fields, self.cur().pos, self.cur().line, self.cur().col)
        return None

    def parse_enhanced_match_pattern(self):
        """Parse match pattern with optional guard clause."""
        pattern = self.parse_match_pattern_atom()
        patterns = [pattern]
        
        # Handle | alternatives
        while self.opt("|"):
            alt_pattern = self.parse_match_pattern_atom()
            patterns.append(alt_pattern)
        
        # Handle guard clause
        guard = None
        if self.opt("if"):
            guard = self.parse_expr()
        
        return EnhancedPattern(patterns, guard, self.cur().pos, self.cur().line, self.cur().col)

    def parse_if_expression(self, cond: Any) -> Any:
        """Parse if expression for use in expressions."""
        self.eat("{")
        then_expr = self.parse_expr()
        self.eat("}")
        self.eat("else")
        if self.cur().kind == "{":
            self.eat("{")
            else_expr = self.parse_expr()
            self.eat("}")
        else:
            else_expr = self.parse_unary()  # Parse a single expression
        return IfExpression(cond, then_expr, else_expr, cond.pos, cond.line, cond.col)

    def parse_string_interpolation(self, tok: Token) -> StringInterpolation:
        """Parse string interpolation like 'hello {name}'."""
        raw = tok.text
        parts = []
        exprs = []
        
        i = 0
        while i < len(raw):
            # Find next interpolation start
            next_brace = i
            while next_brace < len(raw):
                next_brace = raw.find('{', next_brace)
                if next_brace == -1:
                    break
                # Check if this is an escaped brace ({{)
                if next_brace + 1 < len(raw) and raw[next_brace + 1] == '{':
                    # Skip escaped brace
                    next_brace += 2
                    continue
                break
            if next_brace == -1:
                # No more interpolations, add remaining text
                if i < len(raw):
                    # Process escaped braces in the final text part
                    text_part = raw[i:]
                    text_part = text_part.replace("{{", "{").replace("}}", "}")
                    parts.append(text_part)
                # Ensure invariant holds - if we have expressions but no trailing text, add empty string
                elif exprs and len(parts) == len(exprs):
                    parts.append("")
                break
            
            # Add text before interpolation
            if next_brace > i:
                # Process escaped braces in the text part
                text_part = raw[i:next_brace]
                text_part = text_part.replace("{{", "{").replace("}}", "}")
                parts.append(text_part)
            elif next_brace == i:
                # Interpolation at current position - add empty string to maintain invariant
                parts.append("")
            
            # Find matching closing brace
            brace_depth = 1
            j = next_brace + 1
            while j < len(raw) and brace_depth > 0:
                if raw[j] == '{':
                    brace_depth += 1
                elif raw[j] == '}':
                    # Check for escaped closing brace (}})
                    if j + 1 < len(raw) and raw[j + 1] == '}':
                        # Skip the escaped brace
                        j += 1
                    else:
                        brace_depth -= 1
                        if brace_depth == 0:
                            break
                j += 1
            
            if brace_depth > 0:
                self._err("unclosed interpolation brace", tok)
                raise ParseError(self.errors[-1])
            
            # Extract expression inside braces
            expr_text = raw[next_brace + 1:j]
            if not expr_text:
                self._err("empty interpolation", tok)
                raise ParseError(self.errors[-1])
            
            # Save current parser state
            saved_i = self.i
            saved_toks = self.toks
            
            # Create temporary tokens for the expression
            try:
                temp_tokens = lex(expr_text, f"<interpolation at {tok.line}:{tok.col}>")
                self.toks = temp_tokens
                self.i = 0
                expr = self.parse_expr()
                if self.errors:
                    raise ParseError(self.errors[-1])
                
                # Ensure we consumed all tokens - no partial parses allowed
                if self.i < len(self.toks):
                    next_tok = self.toks[self.i]
                    raise ParseError(f"Unexpected token after interpolation: {next_tok.kind} at {next_tok.line}:{next_tok.col}")
            finally:
                # Restore parser state
                self.toks = saved_toks
                self.i = saved_i
            
            exprs.append(expr)
            i = j + 1
        
        return StringInterpolation(parts, exprs, tok.pos, tok.line, tok.col)


def parse(src: str, filename: str = "<input>"):
    """Execute the `parse` routine.
    
    Parameters:
        src: Astra source text to process.
        filename: Filename context used for diagnostics or path resolution.
    
    Returns:
        Value produced by the routine, if any.
    """
    return Parser(src, filename=filename).parse_program()
