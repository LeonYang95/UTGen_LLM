import os
import subprocess
import sys
import json
from tqdm import tqdm
sys.path.extend(['.', '..'])
from utils.JavaAnalyzer import *

d4j_project_home = '/Users/yanglin/Documents/Projects/data/defects4j/d4j_projects'


def file_by_sig(method_signature):
    cls_sig = method_signature.split('::')[0]
    sig_tks = cls_sig.split('.')
    pkg_path = os.path.sep.join(sig_tks[:-1])
    cls_path = sig_tks[-1] + '.java'
    return os.path.join(pkg_path, cls_path)


def dir_by_pkg(method_signature):
    cls_sig = method_signature.split('::')[0]
    sig_tks = cls_sig.split('.')
    pkg_path = os.path.sep.join(sig_tks[:-1])
    return pkg_path


def process_one_bug(bug_id, paths):
    jsondicts = []
    target_project_dir = os.path.join(d4j_project_home, bug_id, 'fixed')
    if not os.path.exists(target_project_dir):
        logger.warning(f'Fixed version of bug id {bug_id} does not exist.')
        return None
    src_dir = paths['src']
    test_dir = paths['test']
    os.chdir(target_project_dir)
    res = subprocess.run(f'defects4j export -p tests.trigger', shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    if res.returncode != 0:
        pass
    else:
        bug_trigger_tests = res.stdout.decode('utf-8').strip().split('\n')
        for tc_signature in bug_trigger_tests:
            test_class_file = os.path.join(target_project_dir, test_dir, file_by_sig(tc_signature))

            # in case there is a junit in package
            if 'junit' in tc_signature:
                tc_signature = tc_signature.replace('junit.', '')
                pass

            source_package_dir = os.path.join(target_project_dir, src_dir, dir_by_pkg(tc_signature))
            test_class_name = tc_signature.split('::')[0].split('.')[-1]
            if os.path.exists(test_class_file) and os.path.exists(source_package_dir):
                source_class_file = None
                for entry in os.listdir(source_package_dir):
                    if entry.endswith('.java') and entry.split('.')[0] in test_class_name:
                        source_class_file = os.path.join(source_package_dir, entry)
                        break
                    pass
                if not source_class_file:
                    logger.warning(f'No source class file found for {tc_signature}.')
                    continue
                    pass
                try:
                    with open(test_class_file, 'r', encoding='utf-8') as reader:
                            test_class = reader.read()
                    with open(source_class_file, 'r', encoding='utf-8') as reader:
                        source_class = reader.read()
                except UnicodeDecodeError:
                    logger.warning(f"{bug_id} contains non-utf-8 encoded files.")
                    continue
                tc_invoked_method_list = extract_method_invocation(test_class, target_class_name=test_class_name,
                                                               target_method_name=tc_signature.split('::')[-1])
                tc_invoked_methods = set(tc_invoked_method_list)
                if not tc_invoked_methods:
                    logger.warning(f'No method invocation found in {tc_signature} for {bug_id} bug.')
                    continue
                if not any([assert_type in tc_invoked_methods for assert_type in ['assertEquals','assertTrue','assertFalse','assertNull','assertNotNull']]):
                    logger.warning(f'No valid assertions found in {tc_signature} for {bug_id} bug.')
                    continue
                src_cls_obj = parse_class_object_from_file_content(source_class,
                                                                   source_class_file.split(os.path.sep)[-1].split('.')[
                                                                       0])

                if not src_cls_obj:
                    logger.warning('Source class is not a class, maybe an abstract class or interface.')
                    continue

                test_cls_obj = parse_class_object_from_file_content(test_class, test_class_name)
                defined_methods = set([m.name for _, m in src_cls_obj.methods.items()])
                intersection_of_methods = tc_invoked_methods.intersection(defined_methods)
                if len(intersection_of_methods) == 1:
                    # 找到了待测函数
                    # 字段：待测函数，包括函数定义和函数体
                    focal_method_name = intersection_of_methods.pop()
                    focal_method_obj = [m for sig, m in src_cls_obj.methods.items() if m.name == focal_method_name][0]
                    test_case_name = tc_signature.split('::')[-1]
                    test_method_obj = [m for sig, m in test_cls_obj.methods.items() if m.name == test_case_name][0]

                    splitted_test_cases = split_test_case_by_assertion(test_method_obj.text)
                    for test_case in splitted_test_cases:
                        jsondict = {
                            'bug_id': bug_id,
                            'version': 'fixed',
                            'focal_method_signature': focal_method_obj.signature,
                            'test_case_signature': tc_signature,
                            'test_file': test_class_file,
                            'source_file': source_class_file,
                            'focal_method': focal_method_obj.text,  # focal method
                            'test_case': test_case,  # test method
                            'parent_test_case':test_method_obj.text,
                            'test_case_invocations': tc_invoked_method_list,
                            'test_class': {
                                'path': test_class_file,
                                'imports': test_cls_obj.imports,  # 引用
                                'fields': [str(f) for k, f in test_cls_obj.fields.items()],  # 定义的属性
                                'methods': [m.signature for k, m in test_cls_obj.methods.items() if
                                            k != test_method_obj.signature],  # 定义的函数
                                'text': test_class  # 完整的测试类
                            },
                            'focal_class': {
                                'path': source_class_file,
                                'imports': src_cls_obj.imports,  # 引用
                                'fields': [str(f) for k, f in src_cls_obj.fields.items()],  # 定义的属性
                                'methods': [m.signature for k, m in src_cls_obj.methods.items() if
                                            k != focal_method_obj.signature],  # 定义的函数
                                'text': source_class  # 完整的待测类
                            }
                        }
                        jsondicts.append(pickle.loads(pickle.dumps(jsondict)))
                    return jsondicts
                pass
            else:
                logger.warning(f'Either {test_class_file} or {source_package_dir} does not exist.')
                continue
                pass
            pass
    return None


if __name__ == '__main__':
    code_base = os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')
    with open(os.path.join(code_base,'bug_path_mapping.json'),'r') as r:
        bug_paths = json.load(r)
    output_writer = open(os.path.join(code_base,'outputs/defects4j_inputs.jsonl'),'w',encoding='utf-8')
    for bug_id, paths in tqdm(bug_paths.items()):
        jsondicts = process_one_bug(bug_id, paths)
        if jsondicts:
            for jsondict in jsondicts:
                output_writer.write(json.dumps(jsondict, ensure_ascii=False) + '\n')
    output_writer.close()
    pass
