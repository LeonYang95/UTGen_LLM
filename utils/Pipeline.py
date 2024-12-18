import os.path

from loguru import logger
from tqdm import *

from entities.CodeEntities import Class
from utils.FileUtils import traverse_files, read_file_with_UTF8
from utils.JavaAnalyzer import parse_class_object_from_file_content
from utils.UTGenerator import BasicGenerator

debug = True


def static_analyze(code_base: str, source_code_path: str) -> list[Class]:
    """
    Performs static analysis on the given code base to extract class information.

    Args:
        code_base (str): The base directory of the code.
        source_code_path (str): The path to the source code within the code base.

    Returns:
        list[Class]: A list of Class objects representing the classes found in the source code.
    """
    classes = []
    source_code_path = os.path.join(code_base, source_code_path)
    files = traverse_files(source_code_path, '.java')
    logger.info(f'Found {len(files)} files in the path {source_code_path}')
    for file in tqdm(files, desc='Traversing files'):
        file_name = os.path.basename(file)

        # Java 类文件中必须包含一个同名的 public class。这里提取文件名方便后面处理多类文件。
        target_class_name, extension = os.path.splitext(file_name)
        try:
            # 确保确实是一个 java 文件
            assert extension == '.java'
            file_content = read_file_with_UTF8(file)
            class_instance = parse_class_object_from_file_content(file_content=file_content,
                                                                  target_class_name=target_class_name)
            if class_instance:
                classes.append(class_instance)
        except AssertionError as ae:
            logger.warning(f"Found unexpected file: {file}. Skipped.")
            continue
        pass
    return classes


def generate_unit_tests(classes: list) -> list:
    generated_test_classes = []
    generator = BasicGenerator()
    if debug:
        classes = classes[:1]
    for class_instance in tqdm(classes, desc='Generating test classes'):
        target_methods = class_instance.public_methods
        if debug:
            target_methods = target_methods[:2]
        logger.info(f'Class {class_instance.name} has {len(target_methods)} to be tested.')
        for method_instance in tqdm(target_methods, desc='Generating'):
            response = generator.generate(
                method_instance=method_instance,
                class_instance=class_instance
            )
            generated_test_classes.append( {
                'focal_method': method_instance.signature,
                'focal_class':class_instance.signature,
                'response': response
            })
            pass

    return generated_test_classes


def post_processing(generated_test_classes: list) -> dict:
    final_test_classes = {}
    return final_test_classes
