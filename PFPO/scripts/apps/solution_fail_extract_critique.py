import copy
import json
import re
import sys
from argparse import ArgumentParser
from datasets import load_dataset
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from glob import glob
import os

from tqdm import tqdm

sys.set_int_max_str_digits(0)

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.apps.utils_execute import check_correctness


def _worker(item):
    if isinstance(item["completion"], str) or isinstance(item["completion"], dict):
        completions = [item["completion"]]
    else:
        completions = item["completion"]

    # if item["input_output"]:
    #     item["input_output"] = json.loads(item["input_output"])

    solutions = []
    results = []
    full_results = []
    # all_outputs = []
    # all_errors = []
    for completion in completions:
        if "corrected_program" not in completion or completion["corrected_program"] is None:
            solutions.append("")
            results.append(False)
            full_results.append([False] * 3)
            continue

        gen_solution = completion["corrected_program"]

        solutions.append(gen_solution)

        if not item["input_output"]:
            continue

        all_results = check_correctness(item["input_output"], gen_solution, timeout=10, debug=False, return_output=False)
        # res, outputs, errors = all_results
        res = all_results
        for tmp in res:
            if (not isinstance(tmp, bool)) and (not isinstance(tmp, int)):
                print(tmp, tmp.__class__.__name__)
        res = [bool(tmp) if (not isinstance(tmp, bool)) and (not isinstance(tmp, int)) else tmp for tmp in res]
        if all(item is True for item in res) is True:
            results.append(True)
        else:
            results.append(False)
        full_results.append(res)
        # all_outputs.append(outputs)
        # all_errors.append(errors)
        # assert len(res) == len(outputs) == len(errors), (len(res), len(outputs), len(errors))

    item["pred"] = solutions if len(solutions) > 1 else solutions[0]
    if results:
        item["res"] = results
        item["full_res"] = full_results
        # item["outputs"] = all_outputs
        # item["errors"] = all_errors

    return item


def main():
    """
    This script takes the GPT-4 completion file with json object as the response format, where the returned json contains two fields:
    - feedback: the critique for the incorrect program.
    - corrected_program: the corrected program.

    THe inputs file is generated by `pp_critique_difficulty` script.
    :return:
    """
    parser = ArgumentParser()
    parser.add_argument("--completion_file", type=str)
    parser.add_argument("--output_file", type=str)
    parser.add_argument("--num_workers", type=int, default=4)
    args = parser.parse_args()

    if os.path.exists(args.completion_file):
        data = [json.loads(line) for line in open(args.completion_file).readlines()]
    else:
        data = []
        item_id2data_id = {}
        for file in glob(args.completion_file):
            print(file)
            tmp = [json.loads(line) for line in open(file).readlines()]
            for item in tmp:
                item_id = item["problem_id"]
                if item_id not in item_id2data_id:
                    item_id2data_id[item_id] = len(data)
                    data.append(item)
                else:
                    new_completions = item["completion"]
                    if isinstance(new_completions, str):
                        new_completions = [new_completions]

                    if isinstance(data[item_id2data_id[item_id]]["completion"], list):
                        data[item_id2data_id[item_id]]["completion"].extend(new_completions)
                    else:
                        data[item_id2data_id[item_id]]["completion"] = [data[item_id2data_id[item_id]]["completion"]] + new_completions

    new_data = []
    parsing_error = 0
    for item in tqdm(data):
        if isinstance(item["completion"], str):
            try:
                item["completion"] = json.loads(item["completion"])
            except:
                # print(f"Parsing error: {item['completion']}")
                parsing_error += 1
        if isinstance(item["completion"], dict):
            new_data.append(item)
    data = new_data
    print(f"Total number of items: {len(data)}")
    print(f"Total number of parsing error: {parsing_error}")

    missing = 0
    corr = 0
    corr_at_k = 0
    pbar = tqdm(data)

    outputs = []
    with ThreadPoolExecutor(max_workers=args.num_workers) as executor:
        futures = []
        for _input in pbar:
            future = executor.submit(_worker, _input)
            futures.append(future)
            pbar.update()

        for future in tqdm(as_completed(futures), total=len(futures), desc="Collecting results"):
            outputs.append(future.result())

    for item in outputs:
        if "res" in item:
            if item["res"][0] is True:
                corr += 1
            if any(item["res"]):
                corr_at_k += 1
        else:
            missing += 1

    print(f"Missing: {missing / len(outputs)}")
    print(f"Correct: {corr / len(outputs)}")
    print(f"Correct at k: {corr_at_k / len(outputs)}")
    json.dump(outputs, open(args.output_file, "w"), ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
