from __future__ import annotations

from astra.ast import *
from astra.lexer import Token, lex


class ParseError(SyntaxError):
    pass


BIN_PREC = {
    "||": 1,
    "&&": 2,
    "==": 3,
    "!=": 3,
    "<": 4,
    "<=": 4,
    ">": 4,
    ">=": 4,
    "+": 5,
    "-": 5,
    "*": 6,
    "/": 6,
    "%": 6,
}

ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%="}


class Parser:
    def __init__(self, src: str, filename: str = "<input>"):
        self.filename = filename
        self.toks = lex(src, filename=filename)
        self.i = 0
        self.errors: list[str] = []

    def cur(self) -> Token:
        return self.toks[self.i]

    def peek(self, n: int = 1) -> Token:
        idx = min(self.i + n, len(self.toks) - 1)
        return self.toks[idx]

    def _err(self, msg: str, tok: Token | None = None) -> None:
        t = tok or self.cur()
        self.errors.append(f"{self.filename}:{t.line}:{t.col}: {msg}")

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

    def recover(self) -> None:
        sync = {";", "}", "fn", "struct", "enum", "EOF"}
        while self.cur().kind not in sync:
            self.i += 1
        if self.cur().kind in {";", "}"}:
            self.i += 1

    def parse_program(self) -> Program:
        items: list[Any] = []
        while self.cur().kind != "EOF":
            try:
                item = self.parse_top_level()
                if item is not None:
                    items.append(item)
            except ParseError:
                self.recover()
        if self.errors:
            raise ParseError("\n".join(self.errors))
        return Program(items)

    def _collect_doc(self) -> str:
        lines: list[str] = []
        j = self.i - 1
        while j >= 0 and self.toks[j].kind == "DOC_COMMENT":
            lines.append(self.toks[j].text)
            j -= 1
        return "\n".join(reversed(lines))

    def parse_top_level(self):
        is_pub = bool(self.opt("pub"))
        if self.cur().kind == "import":
            return self.parse_import()
        if self.cur().kind == "struct":
            return self.parse_struct(is_pub)
        if self.cur().kind == "enum":
            return self.parse_enum(is_pub)
        if self.cur().kind == "type":
            return self.parse_type_alias()
        if self.cur().kind == "fn":
            return self.parse_fn(is_pub)
        raise ParseError(f"{self.filename}:{self.cur().line}:{self.cur().col}: unexpected top-level token {self.cur().kind}")

    def parse_import(self) -> ImportDecl:
        tok = self.eat("import")
        path = [self.eat("IDENT").text]
        while self.opt("::"):
            path.append(self.eat("IDENT").text)
        alias = None
        if self.opt("as"):
            alias = self.eat("IDENT").text
        self.opt(";")
        return ImportDecl(path, alias, tok.pos, tok.line, tok.col)

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

    def parse_fn(self, is_pub: bool = False) -> FnDecl:
        fn_tok = self.eat("fn")
        name = self.eat("IDENT").text
        generics = self._parse_generics()
        self.eat("(")
        params: list[tuple[str, str]] = []
        if self.cur().kind != ")":
            params.append((self.eat("IDENT").text, self.parse_type()))
            while self.opt(","):
                params.append((self.eat("IDENT").text, self.parse_type()))
        self.eat(")")
        self.eat("->")
        ret = self.parse_type()
        body = self.parse_block()
        return FnDecl(name, generics, params, ret, body, pub=is_pub, doc=self._collect_doc(), pos=fn_tok.pos, line=fn_tok.line, col=fn_tok.col)

    def parse_struct(self, is_pub: bool = False) -> StructDecl:
        tok = self.eat("struct")
        name = self.eat("IDENT").text
        generics = self._parse_generics()
        self.eat("{")
        fields: list[tuple[str, str]] = []
        while self.cur().kind != "}":
            fname = self.eat("IDENT").text
            ftype = self.parse_type()
            fields.append((fname, ftype))
            self.opt(",")
        self.eat("}")
        return StructDecl(name, generics, fields, [], pub=is_pub, doc=self._collect_doc(), pos=tok.pos, line=tok.line, col=tok.col)

    def parse_enum(self, is_pub: bool = False) -> EnumDecl:
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
        return EnumDecl(name, generics, variants, pub=is_pub, doc=self._collect_doc(), pos=tok.pos, line=tok.line, col=tok.col)

    def parse_type_alias(self) -> TypeAliasDecl:
        tok = self.eat("type")
        name = self.eat("IDENT").text
        generics = self._parse_generics()
        self.eat("=")
        target = self.parse_type()
        self.opt(";")
        return TypeAliasDecl(name, generics, target, tok.pos, tok.line, tok.col)

    def parse_type(self) -> str:
        if self.opt("&"):
            mut = "mut " if self.opt("mut") else ""
            return f"&{mut}{self.parse_type()}"
        if self.opt("["):
            inner = self.parse_type()
            self.eat("]")
            return f"[{inner}]"
        if self.opt("fn"):
            self.eat("(")
            args: list[str] = []
            if self.cur().kind != ")":
                args.append(self.parse_type())
                while self.opt(","):
                    args.append(self.parse_type())
            self.eat(")")
            self.eat("->")
            return f"fn({', '.join(args)}) -> {self.parse_type()}"
        name = self.eat("IDENT").text
        if self.opt("<"):
            args = [self.parse_type()]
            while self.opt(","):
                args.append(self.parse_type())
            self.eat(">")
            return f"{name}<{', '.join(args)}>"
        return name

    def parse_block(self) -> list[Any]:
        self.eat("{")
        body: list[Any] = []
        while self.cur().kind != "}":
            if self.cur().kind == "EOF":
                self._err("unexpected EOF while parsing block")
                raise ParseError(self.errors[-1])
            try:
                body.append(self.parse_stmt())
            except ParseError:
                self.recover()
        self.eat("}")
        return body

    def parse_stmt(self):
        tok = self.cur()
        if self.opt("let"):
            is_mut = bool(self.opt("mut"))
            name_tok = self.eat("IDENT")
            type_name = None
            if self.opt(":"):
                type_name = self.parse_type()
            self.eat("=")
            expr = self.parse_expr()
            self.eat(";")
            return LetStmt(name_tok.text, expr, is_mut, type_name, tok.pos, tok.line, tok.col)
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
            expr = self.parse_expr()
            body = self.parse_block()
            init = LetStmt(ident.text, Name("<iter>", ident.pos, ident.line, ident.col), True, None, ident.pos, ident.line, ident.col)
            return ForStmt(init, expr, None, body, tok.pos, tok.line, tok.col)
        init = None
        if self.cur().kind != ";":
            if self.cur().kind == "let":
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
            pattern = self.parse_expr()
            self.eat("=>")
            body = self.parse_block()
            arms.append((pattern, body))
        self.eat("}")
        return MatchStmt(expr, arms, tok.pos, tok.line, tok.col)

    def parse_expr(self, min_prec: int = 1):
        left = self.parse_unary()
        while self.cur().kind in BIN_PREC and BIN_PREC[self.cur().kind] >= min_prec:
            op_tok = self.eat(self.cur().kind)
            prec = BIN_PREC[op_tok.kind]
            right = self.parse_expr(prec + 1)
            left = Binary(op_tok.kind, left, right, op_tok.pos, op_tok.line, op_tok.col)
        return left

    def parse_unary(self):
        if self.cur().kind in {"-", "!", "~", "&", "*"}:
            tok = self.eat(self.cur().kind)
            expr = self.parse_unary()
            return Unary(tok.kind, expr, tok.pos, tok.line, tok.col)
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
        if self.opt("INT"):
            return Literal(int(tok.text), tok.pos, tok.line, tok.col)
        if self.opt("FLOAT"):
            return Literal(float(tok.text), tok.pos, tok.line, tok.col)
        if self.opt("STR"):
            return Literal(tok.text, tok.pos, tok.line, tok.col)
        if self.opt("CHAR"):
            return Literal(tok.text, tok.pos, tok.line, tok.col)
        if self.opt("BOOL"):
            return BoolLit(tok.text == "true", tok.pos, tok.line, tok.col)
        if self.opt("nil"):
            return NilLit(tok.pos, tok.line, tok.col)
        if self.opt("IDENT"):
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
    return Parser(src, filename=filename).parse_program()
