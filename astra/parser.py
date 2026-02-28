from astra.ast import *
from astra.lexer import lex

class Parser:
    def __init__(self, src: str):
        self.toks = lex(src)
        self.i = 0

    def cur(self):
        return self.toks[self.i]

    def eat(self, kind: str):
        t = self.cur()
        if t.kind != kind:
            raise SyntaxError(f"Expected {kind}, got {t.kind}")
        self.i += 1
        return t

    def opt(self, kind: str):
        if self.cur().kind == kind:
            self.i += 1
            return True
        return False

    def parse_program(self):
        items = []
        while self.cur().kind != "EOF":
            items.append(self.parse_fn())
        return Program(items)

    def parse_fn(self):
        self.eat("fn")
        name = self.eat("IDENT").text
        generics = []
        if self.opt("<"):
            generics.append(self.eat("IDENT").text)
            while self.opt(","):
                generics.append(self.eat("IDENT").text)
            self.eat(">")
        self.eat("(")
        params = []
        if self.cur().kind != ")":
            params.append((self.eat("IDENT").text, self.eat("IDENT").text))
            while self.opt(","):
                params.append((self.eat("IDENT").text, self.eat("IDENT").text))
        self.eat(")")
        self.eat("->")
        ret = self.eat("IDENT").text
        self.eat("{")
        body = []
        while self.cur().kind != "}":
            body.append(self.parse_stmt())
        self.eat("}")
        return FnDecl(name, generics, params, ret, body)

    def parse_stmt(self):
        if self.opt("let"):
            name = self.eat("IDENT").text
            self.eat("=")
            expr = self.parse_expr()
            self.eat(";")
            return LetStmt(name, expr)
        if self.opt("return"):
            if self.cur().kind == ";":
                self.eat(";")
                return ReturnStmt(None)
            e = self.parse_expr(); self.eat(";")
            return ReturnStmt(e)
        if self.opt("if"):
            cond = self.parse_expr(); self.eat("{")
            then_body=[]
            while self.cur().kind!="}": then_body.append(self.parse_stmt())
            self.eat("}")
            else_body=[]
            if self.opt("else"):
                self.eat("{")
                while self.cur().kind!="}": else_body.append(self.parse_stmt())
                self.eat("}")
            return IfStmt(cond, then_body, else_body)
        if self.opt("while"):
            cond=self.parse_expr(); self.eat("{")
            body=[]
            while self.cur().kind!="}": body.append(self.parse_stmt())
            self.eat("}")
            return WhileStmt(cond, body)
        e = self.parse_expr(); self.eat(";")
        return ExprStmt(e)

    def parse_expr(self):
        left = self.parse_atom()
        while self.cur().kind in {"+","-","*","/","==","!=","<",">","<=",">="}:
            op = self.eat(self.cur().kind).kind
            right = self.parse_atom()
            left = Binary(op, left, right)
        return left

    def parse_atom(self):
        if self.cur().kind == "INT":
            return Literal(int(self.eat("INT").text))
        if self.cur().kind == "STR":
            return Literal(self.eat("STR").text)
        if self.cur().kind == "IDENT":
            name = self.eat("IDENT").text
            if self.opt("("):
                args=[]
                if self.cur().kind != ")":
                    args.append(self.parse_expr())
                    while self.opt(","): args.append(self.parse_expr())
                self.eat(")")
                return Call(name,args)
            return Name(name)
        if self.opt("("):
            e = self.parse_expr(); self.eat(")"); return e
        raise SyntaxError(f"Unexpected atom: {self.cur().kind}")

def parse(src: str):
    return Parser(src).parse_program()
