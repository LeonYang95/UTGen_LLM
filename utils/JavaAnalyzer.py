import pickle

import tree_sitter_java as ts_java
from loguru import logger
from tree_sitter import Parser, Language, Node

from entities.CodeEntities import Method, Class, Field

# Initialize the parser with the Java language
parser = Parser(Language(ts_java.language()))


def get_modifier(node: Node) -> str:
    return ' '.join([n.text.decode('utf-8') for n in node.children if n.type == 'modifiers'])


def _find_package_name(root_node: Node) -> str:
    # 查找 package 定义
    package_decl_node = next(filter(lambda n: n.type == 'package_declaration', root_node.children), None)

    if package_decl_node:
        try:
            assert isinstance(package_decl_node, Node)
            assert package_decl_node.child(1).type == 'scoped_identifier'  # 防止 magic number 出错
            pkg_name = package_decl_node.child(1).text.decode('utf-8')
        except AssertionError:
            # just in case.
            logger.error(
                f'Package declaration node is not as expected. Expected: package_declaration, got: {package_decl_node.type}; Expected child type: scoped_identifier, got: {package_decl_node.child(1).type}.')
            pkg_name = ''
        pass
    else:
        pkg_name = ''

    return pkg_name


def _find_class_declaration_node(root_node: Node, target_class_name: [str | None]) -> [None | Node]:
    # 查找目标类定义节点
    class_decl_node = None
    class_decl_nodes = [n for n in root_node.children if n.type == 'class_declaration']
    if target_class_name:
        # 如果有目标类的名字（根据文件名获得），那么根据名字查找，应该只有一个，用 next 获取
        class_decl_node = next(
            filter(lambda n: n.child_by_field_name('name').text.decode('utf-8') == target_class_name, class_decl_nodes),
            None)
    elif len(class_decl_nodes) >= 1:
        # 没有设定目标名字，默认取第一个 public 且非 abstract 的 class node。Interface 是另外的节点定义类型，在过滤 class_declaration 时已经过滤掉了。
        for node in class_decl_nodes:
            modifiers = next(filter(lambda n: n.type == 'modifiers', node.children), None)
            if modifiers:
                modifier_text = modifiers.text.decode('utf-8')
                if 'public' in modifier_text and 'abstract' not in modifier_text:
                    class_decl_node = node
                    break

    # 判断是否找到
    if not class_decl_node:
        logger.warning(f'Class declaration not found. Please refer to the debug information for debugging.')
        logger.debug(root_node.text.decode('utf-8'))

    return class_decl_node


def _find_imports(root_node: Node) -> list[str]:
    import_nodes = [n for n in root_node.children if n.type == 'import_declaration']
    return [n.text.decode('utf-8') for n in import_nodes] if import_nodes else []


def method_decl_node_to_method_obj(node: Node, pkg_name: str, class_name: str, ) -> Method:
    """
    Converts a method declaration node to a Method object.

    Args:
        node (Node): The method declaration node.
        pkg_name (str): The package name of the class containing the method.
        class_name (str): The name of the class containing the method.

    Returns:
        Method: An object representing the method.
    """
    docstring = node.prev_sibling.text.decode('utf-8') if node.prev_sibling.type == 'block_comment' else ''
    modifier = get_modifier(node)
    method_text = node.text.decode('utf-8')
    parameter_nodes = [n for n in node.child_by_field_name('parameters').children if n.type not in ['(', ')', ',']]
    parameters = []
    for p in parameter_nodes:
        if p.child_by_field_name('name') and p.child_by_field_name('type'):
            parameters.append(
                Field(
                    name=p.child_by_field_name('name').text.decode('utf-8'),
                    type=p.child_by_field_name('type').text.decode('utf-8'),
                    modifier='',
                    value='',
                    docstring=''
                ))
        else:
            parameters.append(
                Field(
                    name=p.text.decode('utf-8'),
                    type='',
                    modifier='',
                    value='',
                    docstring='',
                    text=p.text.decode('utf-8')
                )
            )

    return_type = node.child_by_field_name('type').text.decode('utf-8')
    return Method(
        name=node.child_by_field_name('name').text.decode('utf-8'),
        modifier=modifier,
        text=method_text,
        return_type=return_type,
        params=parameters,
        class_sig=pkg_name + '.' + class_name,
        docstring=docstring
    )


def field_decl_node_to_field_obj(node: Node) -> [Field | None]:
    """
    Converts a field declaration node to a Field object.

    Args:
        node (Node): The field declaration node.

    Returns:
        Field | None: An object representing the field, or None if no declarator is found.
    """
    docstring = node.prev_sibling.text.decode('utf-8') if node.prev_sibling.type == 'block_comment' else ''
    modifier = get_modifier(node)
    type = node.child_by_field_name('type').text.decode('utf-8')
    declarator = node.child_by_field_name('declarator')
    if declarator:
        name = declarator.child_by_field_name('name').text.decode('utf-8')
        value_node = declarator.child_by_field_name('value')
        value = value_node.text.decode('utf-8') if value_node else ''
        return Field(
            docstring=docstring,
            name=name,
            modifier=modifier,
            type=type,
            value=value,
            text=node.text.decode('utf-8')
        )
    else:
        logger.warning(f"No declarator found for {node.text.decode('utf-8')}")
        return None


def parse_class_object_from_file_content(file_content: str, target_class_name: [str | None] = None) -> [Class | None]:
    """
    Parses the class object from the given file content.

    Args:
        file_content (str): The content of the file to parse.
        target_class_name (str | None): The name of the target class to find. If None, the first public non-abstract class is used.

    Returns:
        Class | None: An object representing the class, or None if the class declaration is not found.
    """
    tree = parser.parse(bytes(file_content, 'utf-8'))
    pkg_name = _find_package_name(tree.root_node)
    class_decl_node = _find_class_declaration_node(tree.root_node, target_class_name)
    imports = _find_imports(tree.root_node)
    if not class_decl_node:
        return None

    superclass_node = class_decl_node.child_by_field_name('superclass')
    if superclass_node:
        superclass = class_decl_node.child_by_field_name('superclass').text.decode('utf-8')
    else:
        superclass = ''

    super_interface_node = class_decl_node.child_by_field_name('interfaces')
    if super_interface_node:
        interface = class_decl_node.child_by_field_name('interfaces').text.decode('utf-8')
    else:
        interface = ''

    class_obj = Class(
        package_name=pkg_name,
        name=class_decl_node.child_by_field_name('name').text.decode('utf-8'),
        modifier=get_modifier(class_decl_node),
        text=class_decl_node.text.decode('utf-8'),
        imports=imports,
        interface=interface,
        superclass=superclass
    )

    class_body = class_decl_node.child_by_field_name('body')
    for child in class_body.children:
        if child.type == 'method_declaration':
            # 只接受块注释的 docstring
            method_obj = method_decl_node_to_method_obj(child, pkg_name, class_obj.name)
            class_obj.add_method(method_obj)
        elif child.type == 'field_declaration':
            field_obj = field_decl_node_to_field_obj(child)
            if field_obj: class_obj.add_field(field_obj)
            pass

    return class_obj


def _find_invoked_method_names(method_decl_node: Node) -> list[str]:
    invocation_nodes = []
    query = Language(ts_java.language()).query("(method_invocation name: (_) @name)")
    cand_nodes = query.captures(method_decl_node)
    if 'name' not in cand_nodes:
        return []
    for node in cand_nodes['name']:
        invocation_nodes.append(node.text.decode('utf-8'))
    return invocation_nodes


def extract_method_invocation(file_content: str, target_class_name: [None | str] = None,
                              target_method_name: [None | str] = None) -> list:
    tree = parser.parse(bytes(file_content, 'utf-8'))
    method_invocations = []
    cls_decl_node = _find_class_declaration_node(tree.root_node, target_class_name)
    if cls_decl_node:
        cls_body_node = cls_decl_node.child_by_field_name('body')
        for child in cls_body_node.children:
            if child.type == 'method_declaration':
                method_name = child.child_by_field_name('name').text.decode('utf-8')
                if target_method_name and method_name == target_method_name:
                    method_invocations = _find_invoked_method_names(child)
                    break
    return method_invocations
    pass


def extract_assertion_from_response(response: str):
    lines = response.split('\n')
    in_block = False
    cand_lines = []
    for line in lines:
        line = line.strip()
        if line.startswith('```'):
            if in_block:
                break
            else:
                in_block = True
                continue
        else:
            if in_block:
                if line.startswith('Assert'):
                    cand_lines.append(line[7:])
                else:
                    cand_lines.append(line)
            else:
                continue
    return '\n'.join(cand_lines)


def replace_assertion(test_prefix: str, new_assertion: str) -> str:
    new_test_case = ''
    assertion_to_be_replaced = None

    # 避免出现语法错误
    test_prefix = test_prefix.replace('<expected_value>', '"<expected_value>"')

    # 组装一个测试类，方便 parsing
    tmp_cls = 'public class ABC{' + test_prefix + '}'

    tree = parser.parse(bytes(tmp_cls, 'utf-8'))
    method_decl_node = tree.root_node.children[0].child_by_field_name('body').children[1]
    method_body_node = method_decl_node.child_by_field_name('body')
    query = Language(ts_java.language()).query("(method_invocation name: (identifier) @name)")
    method_invocation_nodes = query.captures(method_body_node)

    # 根据调用函数的名字追溯 statement
    names = method_invocation_nodes['name']
    for name in names:
        if name.text.decode('utf-8') == 'assertEquals':
            assertion_to_be_replaced = name.parent.parent
            assert assertion_to_be_replaced.type == 'expression_statement'
            assertion_to_be_replaced = assertion_to_be_replaced.text.decode('utf-8')
            break

    if not assertion_to_be_replaced:
        logger.error(f'No assertEquals statement found in {test_prefix}')
        pass
    else:
        new_test_case = test_prefix.replace(assertion_to_be_replaced, new_assertion)
    return new_test_case


def find_params_in_assertion(assertion: str) -> list[str]:
    params = []
    cls_str = 'public class ABC {\nvoid testA(){\n' + assertion + '\n}\n}'
    tree = parser.parse(bytes(cls_str, 'utf-8'))
    method_decl_node = tree.root_node.children[0].child_by_field_name('body').children[1]
    method_body_node = method_decl_node.child_by_field_name('body')
    try:
        assert len(method_body_node.children) == 3
    except AssertionError:
        logger.warning(f'Assertion statement {assertion} is not as expected. Expected 3 children, got {len(method_body_node.children)}.')
        return []
    method_invocation = method_body_node.children[1].children[0]
    assert method_invocation.type == 'method_invocation'
    argument_list_node = method_invocation.child_by_field_name('arguments')
    for arg in argument_list_node.children:
        if arg.type not in [',', '(', ')']:
            params.append(arg.text.decode('utf-8'))
    return params


def split_test_case_by_assertion(method_str: str) -> list[str]:
    cls_str = 'public class ABC{\n' + method_str + '\n}'
    tree = parser.parse(bytes(cls_str, 'utf-8'))
    ret_methods = [method_str]
    method_decl_node = tree.root_node.children[0].child_by_field_name('body').children[1]
    method_body_node = method_decl_node.child_by_field_name('body')
    query = Language(ts_java.language()).query("(method_invocation name: (_) @name) @invoke")
    assertion_statement_nodes = []
    for child in method_body_node.children:
        if child.type == 'expression_statement':
            method_invocation_nodes = query.captures(child)
            if 'invoke' not in method_invocation_nodes:
                continue
            method_invocation_nodes = method_invocation_nodes['invoke']
            for node in method_invocation_nodes:
                if node.child_by_field_name('name').text.decode('utf-8').lower().startswith('assert'):
                    assertion_statement_nodes.append(child)
                    pass
                else:
                    pass
    if len(assertion_statement_nodes) == 1:
        pass
    else:
        for i in range(len(assertion_statement_nodes)):
            cur_method = pickle.loads(pickle.dumps(method_str))
            cur_assertion = assertion_statement_nodes[i].text.decode('utf-8')
            for j in range(len(assertion_statement_nodes)):
                if j == i: continue
                cur_method = cur_method.replace(assertion_statement_nodes[j].text.decode('utf-8'), '')
            try:
                assert cur_assertion in cur_method
            except AssertionError:
                continue
            # 使用正则表达式去除连续空行
            cleaned_lines = []
            for line in cur_method.split('\n'):
                if line.strip():  # 非空行
                    cleaned_lines.append(line)
                elif cleaned_lines and cleaned_lines[-1].strip():  # 连续空行只保留一个
                    cleaned_lines.append(line)
            cur_method = '\n'.join(cleaned_lines)
            ret_methods.append(pickle.loads(pickle.dumps(cur_method)))
        pass
    return ret_methods
