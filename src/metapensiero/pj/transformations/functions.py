# -*- coding: utf-8 -*-
# :Project:  pj -- function transformations
# :Created:  mer 09 nov 2016 12:59:00 CET
# :Authors:  Andrew Schaaf <andrew@andrewschaaf.com>,
#            Alberto Berti <alberto@metapensiero.it>
# :License:  GNU General Public License version 3 or later
#

import ast
from functools import reduce

from ..js_ast import (
    JSAttribute,
    JSArrowFunction,
    JSAssignmentExpression,
    JSAsyncFunction,
    JSAsyncMethod,
    JSCall,
    JSClassConstructor,
    JSDict,
    JSExpressionStatement,
    JSFunction,
    JSGenFunction,
    JSGenMethod,
    JSGetter,
    JSMethod,
    JSName,
    JSRest,
    JSSetter,
    JSStatements,
    JSThis,
    JSVarStatement,
)
from ..processor.util import body_local_names, walk_under_code_boundary


def _isyield(el):
    return isinstance(el, (ast.Yield, ast.YieldFrom))


def FunctionDef(t, x, fwrapper=None, mwrapper=None):

    is_method = isinstance(t.parent_of(x), ast.ClassDef)
    is_in_method = all(lambda p: isinstance(p, (ast.FunctionDef,
                                                ast.AsyncFunctionDef,
                                                ast.ClassDef)) \
                       for p in t.parents(x, stop_at=ast.ClassDef)) and \
                           isinstance(tuple(t.parents(x, stop_at=ast.ClassDef))[-1],
                                      ast.ClassDef) # Make sure a class is there

    is_generator = reduce(lambda prev, cur: _isyield(cur) or prev,
                          walk_under_code_boundary(x.body), False)

    t.unsupported(x, not is_method and x.decorator_list, "Function decorators are"
                  " unsupported yet")

    t.unsupported(x, len(x.decorator_list) > 1, "No more than one decorator"
                  " is supported")

    if x.args.vararg or x.args.kwonlyargs or x.args.defaults or \
       x.args.kw_defaults or x.args.kwarg:
        t.es6_guard(x, "Arguments definitions other tha plain params require "
                    "ES6 to be enabled")

    t.unsupported(x, x.args.kwarg and x.args.kwonlyargs,
                  "Keyword arguments together with keyword args accumulator"
                  " are unsupported")

    t.unsupported(x, x.args.vararg and (x.args.kwonlyargs or x.args.kwarg),
                  "Having both param accumulator and keyword args is "
                  "unsupported")

    name = x.name
    arg_names = [arg.arg for arg in x.args.args]
    body = x.body

    acc = JSRest(x.args.vararg.arg) if x.args.vararg else None
    defaults = x.args.defaults
    kw = x.args.kwonlyargs
    kwdefs = x.args.kw_defaults
    kw_acc = x.args.kwarg
    if kw:
        kwargs = []
        for k, v in zip(kw, kwdefs):
            if v is None:
                kwargs.append(k.arg)
            else:
                kwargs.append(JSAssignmentExpression(k.arg, v))
    else:
        kwargs = None

    if is_method or (len(arg_names) > 0 and arg_names[0] == 'self'):
        arg_names = arg_names[1:]

    # be sure that the defaults equal in length the args list
    if isinstance(defaults, (list, tuple)) and len(defaults) < len(arg_names):
        defaults = ([None] * (len(arg_names) - len(defaults))) + list(defaults)
    elif defaults is None:
        defaults = [None] * len(arg_names)

    if kw_acc:
        arg_names += [kw_acc.arg]
        defaults += [JSDict((), ())]

    args = []
    for k, v in zip(arg_names, defaults):
        if v is None:
            args.append(k)
        else:
            args.append(JSAssignmentExpression(k, v))


    # local function vars
    local_vars = list(set(body_local_names(body)) - set(arg_names))
    if len(local_vars) > 0:
        local_vars.sort()
        body = [JSVarStatement(
                            local_vars,
                            [None] * len(local_vars))] + body

    if is_generator:
        fwrapper = JSGenFunction
        mwrapper = JSGenMethod

    # If x is a method
    if is_method:
        cls_member_opts = {}
        if x.decorator_list:
            # decorator should be "property" or "<name>.setter" or "classmethod"
            fdeco = x.decorator_list[0]
            if isinstance(fdeco, ast.Name) and fdeco.id == 'property':
                deco = JSGetter
            elif (isinstance(fdeco, ast.Attribute) and  fdeco.attr == 'setter'
                  and isinstance(fdeco.value, ast.Name)):
                deco = JSSetter
            elif isinstance(fdeco, ast.Name) and fdeco.id == 'classmethod':
                deco = None
                cls_member_opts['static'] = True
            else:
                t.unsupported(x, True, "Unsupported method decorator")
        else:
            deco = None

        if name == '__init__':
            result = JSClassConstructor(
                args, body, acc, kwargs
            )
        else:
            mwrapper = mwrapper or deco or JSMethod
            if mwrapper is JSGetter:
                result = mwrapper(
                    name, body,
                    **cls_member_opts
                )
            elif mwrapper is JSSetter:
                t.unsupported(x, len(args) == 0, "Missing argument in setter")
                result = mwrapper(
                    name, args[0], body,
                    **cls_member_opts
                )
            elif mwrapper is JSMethod:
                if name == '__len__':
                    result = JSGetter(
                        'length',
                        body,
                        **cls_member_opts
                    )
                elif name == '__str__':
                    result = JSMethod(
                        'toString',
                        [], body,
                        **cls_member_opts
                    )
                elif name == '__get__':
                    result = JSMethod(
                        'get',
                        [], body,
                        **cls_member_opts
                    )
                elif name == '__set__':
                    result = JSMethod(
                        'set',
                        [], body,
                        **cls_member_opts
                    )
                else:
                    result = mwrapper(
                        name, args, body,
                        acc, kwargs,
                        **cls_member_opts
                    )
            else:
                result = mwrapper(
                    name, args, body,
                    acc, kwargs,
                    **cls_member_opts
                )
    # x is a function
    else:
        if is_in_method and fwrapper is None:
            result = JSStatements([
                JSVarStatement([str(name)], [None]),
                JSArrowFunction(
                    name, args, body, acc, kwargs
                )
            ])
        elif is_in_method and fwrapper is JSGenFunction:
            result = JSStatements([
                fwrapper(
                    name, args, body, acc, kwargs
                ),
                JSExpressionStatement(
                    JSAssignmentExpression(
                        JSName(name),
                        JSCall(
                            JSAttribute(name, 'bind'),
                            [JSThis()]
                        )
                    )
                )
            ])
        else:
            fwrapper = fwrapper or JSFunction

            result = fwrapper(
                name, args, body,
                acc, kwargs
            )
    return result


def AsyncFunctionDef(t, x):
    t.stage3_guard(x, "Async stuff requires 'stage3' to be enabled")
    return FunctionDef(t, x, JSAsyncFunction, JSAsyncMethod)
