from __future__ import annotations
import dataclasses
import re
import pycparser
import pycparser.c_generator
import tempfile
import pathlib
import collections.abc


def is_void(node: pycparser.c_ast.Node) -> bool:
    return isinstance(node.type, pycparser.c_ast.IdentifierType) and node.type.names[0] == "void"

def define_var(var_type: pycparser.c_ast.Node, var_name: str, value: pycparser.c_ast.Node) -> pycparser.c_ast.Decl:
    return pycparser.c_ast.Decl(
        name=var_name,
        quals=[],
        align=[],
        storage=[],
        funcspec=[],
        type=type,
        init=value,
        bitsize=None,
    )

void = pycparser.c_ast.IdentifierType(names=['void'])

def ptr_type(type: pycparser.c_ast.Node) -> pycparser.c_ast.PtrDecl:
    return pycparser.c_ast.PtrDecl(
        quals=[],
        type=pycparser.c_ast.TypeDecl(
            declname="v",
            quals=[],
            align=None,
            type=type,
        ),
    )

void_fn_ptr = pycparser.c_ast.Typename(
    name=None,
    quals=[],
    align=None,
    type=pycparser.c_ast.PtrDecl(
        quals=[],
        type=pycparser.c_ast.FuncDecl(
            args=None,
            type=pycparser.c_ast.TypeDecl(
                declname=None,
                quals=[],
                align=None,
                type=void,
            ),
        ),
    ),
)

@dataclasses.dataclass(frozen=True)
class ParsedFunc:
    name: str
    # Using tuples rather than lists since tuples are covariant
    params: tuple[tuple[str, pycparser.c_ast.Node], ...]
    return_type: pycparser.c_ast.Node
    variadic: bool = False
    stmts: tuple[pycparser.c_ast.Node, ...] = ()

    @staticmethod
    def from_decl(decl: pycparser.c_ast.Decl) -> ParsedFunc:
        return ParsedFunc(
            name=decl.name,
            params=tuple(
                (param_decl.name, param_decl.type)
                for param_decl in decl.type.args.params
                if isinstance(param_decl, pycparser.c_ast.Decl)
            ),
            return_type=decl.type.type,
            variadic=isinstance(decl.type.args.params[-1], pycparser.c_ast.EllipsisParam),
        )

    @staticmethod
    def from_defn(func_def: pycparser.c_ast.FuncDef) -> ParsedFunc:
        return dataclasses.replace(
            ParsedFunc.from_decl(func_def.decl),
            stmts=tuple(func_def.body.block_items) if func_def.body.block_items is not None else (),
        )

    def declaration(self) -> pycparser.c_ast.FuncDecl:
        return pycparser.c_ast.FuncDecl(
            args=pycparser.c_ast.ParamList(
                params=[
                    pycparser.c_ast.Decl(
                        name=param_name,
                        quals=[],
                        align=[],
                        storage=[],
                        funcspec=[],
                        type=pycparser.c_ast.TypeDecl(
                            declname=param_name,
                            quals=[],
                            align=[],
                            type=param_type,
                        ),
                        init=None,
                        bitsize=None,
                    )
                        for param_name, param_type in self.params
                ] + ([pycparser.c_ast.EllipsisParam()] if self.variadic else []),
            ),
            type=pycparser.c_ast.TypeDecl(
                declname=self.name,
                quals=[],
                align=[],
                type=self.return_type,
            ),
        )

    def definition(self) -> pycparser.c_ast.FuncDef:
        return pycparser.c_ast.FuncDef(
            decl=pycparser.c_ast.Decl(
                name=self.name,
                quals=[],
                align=[],
                storage=[],
                funcspec=[],
                type=self.declaration(),
                init=None,
                bitsize=None
            ),
            param_decls=None,
            body=pycparser.c_ast.Compound(
                block_items=self.stmts,
            ),
        )

filename = pathlib.Path("libc_subset.c")
with tempfile.TemporaryDirectory() as _tmpdir:
    tmpdir = pathlib.Path(_tmpdir)
    (tmpdir / filename).write_text(re.sub("/\\*.*?\\*/", "", filename.read_text(), flags=re.DOTALL))
    ast = pycparser.parse_file(tmpdir / filename, use_cpp=False)
generator = pycparser.c_generator.CGenerator()
funcs = [
    ParsedFunc.from_defn(node)
    for node in ast.ext
    if isinstance(node, pycparser.c_ast.FuncDef)
]
func_prefix = "_o_"
func_pointer_declarations = [
    pycparser.c_ast.Decl(
        name=func_prefix + func.name,
        quals=[],
        align=[],
        storage=["static"],
        funcspec=[],
        type=pycparser.c_ast.PtrDecl(
            quals=[],
            type=dataclasses.replace(func, name=func_prefix + func.name).declaration(),
        ),
        init=None,
        bitsize=None,
    )
    for func in funcs
]
setup_function_pointers = ParsedFunc(
    name="setup_function_pointers",
    params=(),
    return_type=pycparser.c_ast.IdentifierType(names=['void']),
    variadic=False,
    stmts=tuple(
        pycparser.c_ast.Assignment(
            op='=',
            lvalue=pycparser.c_ast.ID(name=func_prefix + func.name),
            rvalue=pycparser.c_ast.FuncCall(
                name=pycparser.c_ast.ID(name="dlsym"),
                args=pycparser.c_ast.ExprList(
                    exprs=[
                        pycparser.c_ast.ID(name="RTLD_NEXT"),
                        pycparser.c_ast.Constant(type="string", value='"' + func.name + '"'),
                    ],
                ),
            ),
        )
        for func in funcs
    ),
).definition()
def wrapper_func_body(func: ParsedFunc) -> tuple[pycparser.c_ast.Node, ...]:
    stmts = []
    if func.variadic:
        varargs_stmts = [
            stmt
            for stmt in func.stmts
            if isinstance(stmt, pycparser.c_ast.Decl) and stmt.name == "varargs_size"
        ]
        if not varargs_stmts:
            raise ValueError(f"No `size_t varargs_size = ...;` found for {func.name}")
        stmts.append(varargs_stmts[0])
        # Generates: __builtin_apply((void (*)())_o_open, __builtin_apply_args(), varargs_size)
        uncasted_func_call = pycparser.c_ast.FuncCall(
            name=pycparser.c_ast.ID(name='__builtin_apply'),
            args=pycparser.c_ast.ExprList(
                exprs=[
                    pycparser.c_ast.Cast(
                        to_type=void_fn_ptr,
                        expr=pycparser.c_ast.ID(name=func_prefix + func.name)
                    ),
                    pycparser.c_ast.FuncCall(name=pycparser.c_ast.ID(name='__builtin_apply_args'), args=None),
                    pycparser.c_ast.ID(name='varargs_size'),
                ],
            ),
        )
        if is_void(func.return_type):
            func_call = uncasted_func_call
        else:
            func_call = pycparser.c_ast.UnaryOp(
                op="*",
                expr=pycparser.c_ast.Cast(
                    to_type=ptr_type(func.return_type),
                    expr=uncasted_func_call,
                ),
            )
    else:
        func_call = pycparser.c_ast.FuncCall(
            name=pycparser.c_ast.ID(
                name=func_prefix + func.name,
            ),
            args=pycparser.c_ast.ExprList(
                exprs=[
                    pycparser.c_ast.ID(name=param_name)
                    for param_name, _ in func.params
                ],
            ),
        )
    loggy_stuff = pycparser.c_ast.If(
        cond=pycparser.c_ast.UnaryOp(
            op='!',
            expr=pycparser.c_ast.ID(name='disable_log'),
        ),
        iftrue=pycparser.c_ast.Compound(
            block_items=[
                pycparser.c_ast.FuncCall(
                    name=pycparser.c_ast.ID("fprintf"),
                    args=pycparser.c_ast.ExprList(
                        exprs=[
                            pycparser.c_ast.FuncCall(
                                name=pycparser.c_ast.ID("get_prov_log_file"),
                                args=pycparser.c_ast.ExprList(
                                    exprs=[],
                                ),
                            ),
                            pycparser.c_ast.Constant(type="string", value='"' + func.name +  '\\n"'),
                        ],
                    ),
                ),
            ],
        ),
        iffalse=None,
    )
    if is_void(func.return_type):
        stmts.append(func_call)
        stmts.append(loggy_stuff)
        stmts.append(pycparser.c_ast.Return(expr=None))
    else:
        stmts.append(pycparser.c_ast.Decl(
            name="ret",
            quals=[],
            align=[],
            storage=[],
            funcspec=[],
            type=pycparser.c_ast.TypeDecl(
                declname="ret",
                quals=[],
                align=None,
                type=func.return_type,
            ),
            init=func_call,
            bitsize=None
        ))
        stmts.append(loggy_stuff)
        stmts.append(pycparser.c_ast.Return(expr=pycparser.c_ast.ID(name="ret")))
    return tuple(stmts)

static_args_wrapper_func_declarations = [
    dataclasses.replace(
        func,
        stmts=wrapper_func_body(func),
    ).definition()
    for func in funcs
]
print(generator.visit(pycparser.c_ast.FileAST(ext=[
    *func_pointer_declarations,
    setup_function_pointers,
    *static_args_wrapper_func_declarations,
])))
