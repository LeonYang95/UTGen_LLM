import hashlib
import json
import os
import subprocess
import sys

from loguru import logger

sys.path.extend(['.', '..'])
from utils.JavaAnalyzer import extract_assertion_from_response, replace_assertion, find_params_in_assertion

boolean_expected_value = ['assertTrue', 'assertFalse']
nullable_expected_value = ['assertNull', 'assertNotNull']

if __name__ == '__main__':
    input_file = '/Users/yanglin/Documents/Projects/UTGen_LLM/outputs/logprobs_defects4j/first_round_multiple_responses-RAGGenerator-results.jsonl'
    d4j_project_base = '/Users/yanglin/Documents/Projects/data/defects4j/d4j_projects'

    comparison_file = '/Users/yanglin/Documents/Projects/UTGen_LLM/outputs/defects4j_inputs.jsonl'
    comparison_group = []
    with open(comparison_file, 'r', encoding='utf-8') as reader:
        for line in reader.readlines():
            comparison_group.append(json.loads(line.strip()))

    corrected_ids = set()
    passed_ids = set()
    passed = 0
    total = 0
    regarded_as_passed = 0
    corrected = 0
    with open(input_file, 'r', encoding='utf-8') as reader:
        for line in reader.readlines():
            total += 1
            instance = json.loads(line.strip())
            comparison_instance = comparison_group[instance['id']]
            assert hashlib.md5(comparison_instance['focal_method'].encode('utf-8')).hexdigest() == hashlib.md5(
                instance['focal_method'].encode('utf-8')).hexdigest()
            bug_id = comparison_instance['bug_id']

            if bug_id in ['Mockito_18', 'Mockito_1']:
                total -= 1
                continue

            # if bug_id != 'Math_46':
            #     continue

            test_case_file = comparison_instance['test_file']
            expected_value = instance['expected_value']
            # 替换掉原本的测试断言
            generated_assertion = extract_assertion_from_response(instance['response'])
            is_correct = False
            if expected_value in generated_assertion:
                corrected += 1
                is_correct = True
                corrected_ids.add(instance['id'])
            if expected_value in boolean_expected_value or expected_value in nullable_expected_value:
                new_test_case = instance['test_prefix'].replace('<AssertionPlaceHolder>', generated_assertion)
            else:
                new_test_case = replace_assertion(instance['test_prefix'], generated_assertion)
                if not new_test_case:
                    continue
            new_test_class = comparison_instance['test_class']['text'].replace(comparison_instance['parent_test_case'],
                                                                               new_test_case)
            try:
                # write_test_class(bug_id, 'fixed', new_test_class)
                logger.info(f'bug id :{bug_id}')
                with open(test_case_file, 'w', encoding='utf-8') as writer:
                    writer.write(new_test_class)
                os.chdir(os.path.join(d4j_project_base, bug_id, 'fixed'))
                ret = subprocess.run('defects4j test', shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                res_output = ret.stdout.decode('utf-8')
                if res_output == 'Failing tests: 0\n':
                    passed += 1
                    passed_ids.add(instance['id'])
                    logger.info('Passed')
                    if not is_correct and expected_value not in boolean_expected_value and expected_value not in nullable_expected_value:
                        logger.debug(expected_value + ' vs. '+ generated_assertion)
                else:
                    logger.info('Failed')
                    if is_correct:
                        if expected_value in boolean_expected_value or expected_value in nullable_expected_value:
                            if generated_assertion.startswith(expected_value):
                                logger.warning(
                                    f'The expected assertion generated for {bug_id} is correct, but failed in the test.')
                                regarded_as_passed += 1
                                passed_ids.add(instance['id'])
                        else:
                            if '<expected_value>' in generated_assertion:
                                logger.error(
                                    f'{bug_id} failed execution because expected value is not replaced. Remove from the correct set.')
                            else:
                                params = find_params_in_assertion(generated_assertion)
                                if expected_value in params:
                                    logger.warning(
                                        f'The generated expected value({generated_assertion}) for {bug_id} is correct ({expected_value}), but failed in the test.')
                                    regarded_as_passed += 1
                                    passed_ids.add(instance['id'])
                                else:
                                    corrected -= 1
                                    corrected_ids.remove(instance['id'])
                                    logger.error(bug_id)
                                    logger.error(
                                        f"The expected value is {expected_value}, but got the generated assertion {generated_assertion}.")
                    else:
                        if ret.returncode == 0:
                            print(ret.stdout.decode('utf-8'))
                        else:
                            print(ret.stderr.decode('utf-8'))
                        pass
            finally:
                # No matter what, write back the original class.
                # write_test_class(bug_id, 'fixed', comparison_instance['test_class']['text'])
                with open(test_case_file, 'w', encoding='utf-8') as writer:
                    writer.write(comparison_instance['test_class']['text'])

    logger.info(f'Accuracy: {corrected} / {total} = {corrected / total:.2%}')
    logger.info(f'Pass Rate: {passed} / {total} = {passed / total:.2%}')
    logger.info(
        f'Regarded as passed: {passed + regarded_as_passed} / {total}  = {(regarded_as_passed + passed) / total :.2%}')
    logger.info(f'Corrected IDs: {corrected_ids}')
    logger.info(f'Passed IDs: {passed_ids}')
    logger.info(f'{input_file}')
    pass
