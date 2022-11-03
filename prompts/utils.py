from dataclasses import dataclass
from typing import List, Union
import pandas as pd
import random
import time
import logging
from prompts.example import PromptStr

from prompts.example import Example
from prompts.task_id_to_prompt import task_id_to_prompt

logging.basicConfig(level=logging.INFO)


@dataclass
class PromptConfig:
    question_prefix: str = "Q: "
    answer_prefix: str = "A: "
    final_answer_prefix: str = "The answer is "
    intra_example_sep: str = "\n"
    inter_example_sep: str = "\n\n"
    
    @staticmethod
    def from_args(args):
        return PromptConfig(
            question_prefix=args.question_prefix.replace('\\n', '\n'),
            answer_prefix=args.answer_prefix.replace('\\n', '\n'),
            final_answer_prefix=args.final_answer_prefix.replace('\\n', '\n'),
            intra_example_sep=args.intra_example_sep.replace('\\n', '\n'),
            inter_example_sep=args.inter_example_sep.replace('\\n', '\n'),
        )


@dataclass
class TaskConfig:
    """
    num_examples (int): Number of examples to include in the prompt.
    task_id (str): A unique id for the task. Task id is used to recover task_file. Specifically,
                   data/tasks/task_id.split("_")[0].jsonl should be the task file.
                   The task file should be a jsonl file with two columns: input and target.
    seed (int): Seed for the random number generator used to order examples.
    prompt_config (PromptConfig): Configuration for the prompt.
    max_tokens (int): Maximum number of tokens to be generated by the model.
                      It is task-dependent, because the number of tokens depends on the task.
    """

    task_id: str
    tag: str
    num_examples: int
    max_tokens: int
    timeout: int
    seed: int
    num_questions_per_thread: int
    is_cot_task: bool
    model_name: str
    cached_timestamp: str # reload a cached folder and rerun the error examples
    max_requests_per_min: int
    prompt_config: PromptConfig
    temperature: float = 0.0


def format_prompt(
    prompt_examples: Union[List[Example], PromptStr],
    prompt_config: PromptConfig,
    num_examples: int,
    seed: int,
    is_cot_prompt: bool,
) -> str:
    """Formats the prompt.
    Args:
        prompt (List[Example]): List of examples for the prompt.
        prompt_config (PromptConfig): Configuration for the prompt.
        num_examples (int): Number of examples to include in the prompt.
        seed (int): Seed for random number generator. This will ensure that the same examples are used for each prompt.
        is_cot_prompt (bool): Whether the prompt is a COT prompt.
    Returns:
        str: The prompt str
    """
    if isinstance(prompt_examples, PromptStr):
        return prompt_examples.prompt_str
    # shuffle the examples, but use the same seed for each prompt
    if num_examples == -1:
        num_examples = len(prompt_examples)
    examples = random.Random(seed).sample(prompt_examples, num_examples)
    # format the prompt
    prompt_str = ""
    for example in examples:
        prompt_str += (
            prompt_config.question_prefix + example.question + prompt_config.intra_example_sep
        )  # "Q: " + question + "\n"
        if is_cot_prompt:
            prompt_str += (
                prompt_config.answer_prefix + example.thought + " "
            )  # "A: " + thought + " "
            prompt_str += (
                prompt_config.final_answer_prefix
                + example.answer
                + prompt_config.intra_example_sep
            )  # "The answer is " + answer + "\n"
        else:
            prompt_str += (
                prompt_config.answer_prefix
                + prompt_config.final_answer_prefix
                + example.answer
                + prompt_config.intra_example_sep
            )  # "A: " + answer + "\n"
        prompt_str += prompt_config.inter_example_sep  # "\n\n"

    # NOTE: the last inter_example_sep is already added here, so we can directly add the input
    return prompt_str


def make_task_file_from_config(task_config: TaskConfig) -> pd.DataFrame:
    """Generates a task file from a task config (TaskConfig).

    Returns:
        pd.DataFrame: A dataframe with the columns "question" and "answer".
        - For each row:
            * `question` is the concatenation of prompt followed by the input.
            * `answer` is the target answer.
    """
    # read the task file

    task_file_path = f"data/tasks/{task_config.task_id.split('_')[0]}.jsonl"
    import json
    rows = []
    with open(task_file_path, "r") as f:
        for line in f:
            rows.append(json.loads(line))
    
    task_df = pd.DataFrame(rows)
        
    # task_df = pd.read_json(task_file_path, lines=True, orient="records")

    # format the prompt
    if isinstance(task_id_to_prompt[task_config.task_id], PromptStr):
        prompt_str = task_id_to_prompt[task_config.task_id].prompt_str
    else:
        prompt_str = format_prompt(
            prompt_examples=task_id_to_prompt[task_config.task_id],
            prompt_config=task_config.prompt_config,
            num_examples=task_config.num_examples,
            seed=task_config.seed,
            is_cot_prompt=task_config.is_cot_task,
        )

    is_non_code_model = "code" not in task_config.model_name
    # add the prompt to the task file
    task_df["question"] = (
        prompt_str
        + task_config.prompt_config.question_prefix
        + task_df["input"]
        + task_config.prompt_config.intra_example_sep
        + (task_config.prompt_config.answer_prefix.strip() if is_non_code_model else task_config.prompt_config.answer_prefix)
    )
    # davinci doesn't like prompts that end with a space
    task_df["answer"] = task_df["target"]
    return task_df[["question", "answer"]]
