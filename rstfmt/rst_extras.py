"""
This module handles adding constructs to the reST parser in a way that makes sense for rstfmt.
Nonstandard directives and roles are inserted into the tree unparsed (wrapped in custom node classes
defined here) so we can format them the way they came in without without caring about what they
would normally expand to.
"""

import importlib
from typing import Any, Dict, Iterator, List, Optional, Tuple, Type, TypeVar

import docutils
import docutils.nodes
import docutils.utils
import sphinx.directives.code
import sphinx.directives.other
import sphinx.domains.changeset
import sphinx.ext.autodoc
import sphinx.ext.autodoc.directive
import sphinx.ext.todo
import sphinx.util.docutils
from docutils.parsers.rst import Directive, directives, roles

# Import these only to load their domain subclasses.
from sphinx.domains import c, cpp, python, std  # noqa: F401

T = TypeVar('T')


class directive(docutils.nodes.Element, docutils.nodes.Inline):
    pass


class role(docutils.nodes.Element):
    pass


class ref_role(docutils.nodes.Element):
    pass


class ReferenceRole(sphinx.util.docutils.ReferenceRole):
    def run(self) -> Tuple[List[docutils.nodes.Node], List[docutils.nodes.system_message]]:
        node = ref_role(
            self.rawtext,
            name=self.name,
            has_explicit_title=self.has_explicit_title,
            target=self.target,
            title=self.title,
        )
        return [node], []


role_aliases = {
    'pep': 'PEP',
    'pep-reference': 'PEP',
    'rfc': 'RFC',
    'rfc-reference': 'RFC',
    'subscript': 'sub',
    'superscript': 'sup',
}


def generic_role(r: str, rawtext: str, text: str, *_: Any, **__: Any) -> Any:
    r = role_aliases.get(r.lower(), r)
    text = docutils.utils.unescape(text, restore_backslashes=True)
    return ([role(rawtext, text=text, role=r)], [])


def _add_directive(
    name: str,
    cls: Type[docutils.parsers.rst.Directive],
    *,
    attrs: Optional[Dict] = None,
    raw: bool = True,
) -> None:
    # We create a new class inheriting from the given directive class to automatically pick up the
    # argument counts and most of the other attributes that define how the directive is parsed, so
    # parsing can happen as normal. The things we change are:
    #
    # - Relax the option spec so an incorrect name doesn't stop formatting and every option comes
    #   through unchanged.
    # - Override the run method to just stick the directive into the tree.
    # - Add a `raw` attribute to inform formatting later on.
    namespace = {
        'option_spec': sphinx.ext.autodoc.directive.DummyOptionSpec(),
        'run': lambda self: [directive(directive=self)],
        'raw': raw,
        **(attrs or {}),
    }
    directives.register_directive(name, type('rstfmt_' + cls.__name__, (cls,), namespace))


def _add_optional_directive(directive_name, directive_cls, importlib_name):
    try:
        module = importlib.import_module(importlib_name)
    except ImportError:
        pass
    else:
        _cls = getattr(module, directive_cls, None)
        if _cls:
            _add_directive(directive_name, _cls)


def _subclasses(cls: Type[T]) -> Iterator[Type[T]]:
    for _c in cls.__subclasses__():
        yield _c
        yield from _subclasses(_c)


def register() -> None:
    for r in [
        # Standard roles (https://docutils.sourceforge.io/docs/ref/rst/roles.html) that don't have
        # equivalent non-role-based markup.
        'math',
        'pep-reference',
        'rfc-reference',
        'subscript',
        'superscript',
    ]:
        roles.register_canonical_role(r, generic_role)

    roles.register_canonical_role('download', ReferenceRole())
    for domain in _subclasses(sphinx.domains.Domain):
        for name, role_callable in domain.roles.items():
            if isinstance(role_callable, sphinx.util.docutils.ReferenceRole):
                roles.register_canonical_role(name, ReferenceRole())
                roles.register_canonical_role(f'{domain.name}:{name}', ReferenceRole())

        for name, directive_cls in domain.directives.items():
            _add_directive(f'{domain.name}:{name}', directive_cls)

    # Take the `py` domain as the implicit default. (TODO: Handle files that change the default.)
    for name, directive_cls in python.PythonDomain.directives.items():
        _add_directive(name, directive_cls)

    non_raw_directives = {
        'admonition',
        'attention',
        'caution',
        'danger',
        'error',
        'hint',
        'important',
        'note',
        'tip',
        'warning',
        # `list-table` directives are parsed into table nodes by default and could be formatted as
        # such, but that's vulnerable to producing malformed tables when the given column widths are
        # too small, so keep them as directives.
        'list-table',
        'tabs',
        'tab',
        'group-tab',
        'code-tab',
    }

    # The role directive is defined in a rather odd way under the hood: although it appears to take
    # one argument and allow options, the class actually specifies that it takes no arguments or
    # options but does have content; it then does its own parsing of arguments and options based on
    # the content. I'm not entirely sure why, but I think it's to handle the case of using some
    # exotic base role that has a body or something. I think just taking an argument is pretty much
    # good enough, though.
    _add_directive('role', Directive, attrs={'required_arguments': 1})
    exclude_directives = {'role'}

    for directive_name, (module, cls_name) in directives._directive_registry.items():
        if directive_name in exclude_directives:
            continue
        module = importlib.import_module(f'docutils.parsers.rst.directives.{module}')
        cls = getattr(module, cls_name)
        _add_directive(directive_name, cls, raw=directive_name not in non_raw_directives)

    _add_directive('glossary', std.Glossary, raw=False)
    _add_directive('literalinclude', sphinx.directives.code.LiteralInclude)
    _add_directive('toctree', sphinx.directives.other.TocTree)
    _add_directive('versionadded', sphinx.domains.changeset.VersionChange)
    _add_directive('only', sphinx.directives.other.Only)
    _add_directive('highlight', sphinx.directives.code.Highlight)
    _add_directive('todo', sphinx.ext.todo.Todo)
    _add_directive('code-block', sphinx.directives.code.CodeBlock)

    for d in set(_subclasses(sphinx.ext.autodoc.Documenter)):
        if d.objtype != 'object':
            _add_directive('auto' + d.objtype, sphinx.ext.autodoc.directive.AutodocDirective, raw=False)

    #####################
    # optional packages #
    #####################
    try:
        import sphinx_tabs.tabs
    except ImportError:
        pass
    else:
        _add_directive('tabs', sphinx_tabs.tabs.TabsDirective, raw=False)
        _add_directive('tab', sphinx_tabs.tabs.TabDirective, raw=False)
        _add_directive('group-tab', sphinx_tabs.tabs.GroupTabDirective, raw=False)
        _add_directive('code-tab', sphinx_tabs.tabs.CodeTabDirective)

    try:
        import sphinx_click
    except ImportError:
        pass
    else:
        _add_directive('click', sphinx_click.ext.ClickDirective)

    try:
        import sphinxarg.ext
    except ImportError:
        pass
    else:
        _add_directive('argparse', sphinxarg.ext.ArgParseDirective)

    try:
        from esp_docs.esp_extensions.include_build_file import IncludeBuildFile
        from esp_docs.generic_extensions.list_filter import ListFilter
    except ImportError:
        pass
    else:
        roles.register_canonical_role('project', ReferenceRole())
        roles.register_canonical_role('project_file', ReferenceRole())
        roles.register_canonical_role('project_raw', ReferenceRole())

        # These are the same as :project:, but kept for backwards compatibility reasons
        roles.register_canonical_role('idf', ReferenceRole())
        roles.register_canonical_role('idf_file', ReferenceRole())
        roles.register_canonical_role('idf_raw', ReferenceRole())

        roles.register_canonical_role('component', ReferenceRole())
        roles.register_canonical_role('component_file', ReferenceRole())
        roles.register_canonical_role('component_raw', ReferenceRole())

        roles.register_canonical_role('example', ReferenceRole())
        roles.register_canonical_role('example_file', ReferenceRole())
        roles.register_canonical_role('example_raw', ReferenceRole())

        roles.register_canonical_role('link_to_translation', ReferenceRole())

        _add_directive('include-build-file', IncludeBuildFile)
        _add_directive('list', ListFilter)

    _add_optional_directive('blockdiag', 'Blockdiag', 'sphinxcontrib.blockdiag')

    _add_optional_directive('packetdiag', 'Packetdiag', 'sphinxcontrib.packetdiag')

    _add_optional_directive('rackdiag', 'Rackdiag', 'sphinxcontrib.rackdiag')

    _add_optional_directive('seqdiag', 'Seqdiag', 'sphinxcontrib.seqdiag')

    _add_optional_directive('wavedrom', 'WavedromDirective', 'sphinxcontrib.wavedrom')

    _add_optional_directive('doxygenstruct', 'DoxygenClassDirective', 'breathe.directives.class_like')
    _add_optional_directive('doxygenfunction', 'DoxygenFunctionDirective', 'breathe.directives.function')

    _add_optional_directive('mermaid', 'Mermaid', 'sphinxcontrib.mermaid')
