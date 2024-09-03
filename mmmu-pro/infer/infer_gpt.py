import re
import ast
import os
import json
from PIL import Image
from tqdm import tqdm
import sys
import json
import sys
from openai import OpenAI
import requests
from concurrent.futures import ThreadPoolExecutor

if len(sys.argv) == 3:
    MODEL = sys.argv[1]
    MODE = sys.argv[2]
else:
    print("Usage: python script.py [MODEL] [MODE], default: python infer_gpt.py gpt-4o-mini cot")
    MODEL = 'gpt-4o-mini'
    MODE = 'cot'
    # sys.exit(1)

API_KEY = 'your_api_key'
WORKERS = 30
NUM = 1730

# Load prompts from YAML file
import yaml
with open("prompts.yaml", "r") as file:
    prompt_config = yaml.safe_load(file)[MODE]

import base64
def replace_images_tokens(input_string):
    for i in range(1, 8):
        question_text = f"<image {i}>"
        query_text = "<image>"
        if question_text in input_string:
            input_string = input_string.replace(question_text, query_text)
    return input_string

def parse_options(options):
    option_letters = [chr(ord("A") + i) for i in range(len(options))]
    choices_str = "\n".join([f"{option_letter}. {option}" for option_letter, option in zip(option_letters, options)])
    return choices_str

def construct_prompt(doc):
    question = doc["question"]
    # Weirdly, data["shuffled_options"] is a string in MMMU Huggingface dataset
    if doc['type']=='Standard(4opts)':
        parsed_options = parse_options(ast.literal_eval(str(doc["options"])))
    elif doc['type']=='Standard(10opts)':
        parsed_options = parse_options(ast.literal_eval(str(doc["shuffled_options"])))
    else:
        print ('error')
    # parsed_options already prepends a newline so no need to add space here
    question = f"{question}\n{parsed_options}\n{prompt_config['Standard']}"
    return question

def mmmu_doc_to_text(doc):
    question = construct_prompt(doc)
    return replace_images_tokens(question)

def origin_mmmu_doc_to_visual(doc):
    prompt = construct_prompt(doc)
    image_tokens = re.findall(r"<image \d+>", prompt)
    # Remove <> and  swap space as _
    image_tokens = [image_token.strip("<>").replace(" ", "_") for image_token in image_tokens]
    # 正常使用
    visual = []
    for image_token in image_tokens:
        path = "dir_to_mmmu_images" + doc[image_token]      #** change your image path here **
        visual.append(path)
    return visual

def vision_mmmu_doc_to_visual(doc):
    visual = []
    # for image_token in image_tokens:
    path = "dir_to_mmmu_pro_images" + doc['id'] + ".png"
    visual.append(path)
    return visual

def load_model(model_name="GPT4", base_url="https://api.01ww.xyz/v1", api_key="zhangge-test", model="gpt-4-turbo-preview"):
    model_components = {}
    model_components['model_name'] = model_name
    model_components['model'] = model
    model_components['base_url'] = base_url
    model_components['api_key'] = api_key
    return model_components

def request(prompt, timeout=120, max_tokens=128, base_url="https://api.01ww.xyz/v1", api_key="zhangge-test", model="gpt-4-turbo-preview", model_name=None):
    client = OpenAI(base_url=base_url, api_key=api_key)
    include_system = False
    response = client.chat.completions.create(
        model=model,
        messages = [{"role": "system", "content": "You're a useful assistant."}] * include_system \
         + [{"role": "user", "content": prompt}],
        stream=False, max_tokens=max_tokens, timeout=timeout)
    return response

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

# Function to create interleaved content of texts and images
def make_interleave_content(texts_or_image_paths):
    content = []
    for text_or_path in texts_or_image_paths:
        if text_or_path.endswith(".jpeg") or text_or_path.endswith(".png"):
            base64_image = encode_image(text_or_path)
            image_elem = {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64_image}"
                }
            }
            content.append(image_elem)
        else:
            text_elem = {
                "type": "text",
                "text": text_or_path
            }
            content.append(text_elem)
    return content

# Function to send request with images and text
def request_with_images(texts_or_image_paths, timeout=60, max_tokens=300, base_url="https://api.openai.com/v1", api_key="123", model="gpt-4o-mini"):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are ChatGPT, a large language model trained by OpenAI, based on the GPT-4 architecture.",
                "role": "user",
                "content": make_interleave_content(texts_or_image_paths)
            }
        ],
        "max_tokens": max_tokens
    }

    response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=timeout)
    return response.json()

def infer(prompts, max_tokens=4096, use_vllm=False, **kwargs):
    model = kwargs.get('model')
    base_url = kwargs.get('base_url')
    api_key = kwargs.get('api_key')
    model_name = kwargs.get('model_name', None)
    
    if isinstance(prompts, list):
        prompts = prompts[0]
    
    try:
        if isinstance(prompts, dict) and 'images' in prompts:
            prompts, images = prompts['prompt'], prompts['images']
            response_tmp = request_with_images([prompts, *images], max_tokens=max_tokens, base_url=base_url, api_key=api_key, model=model)
            response = response_tmp["choices"][0]["message"]["content"]
        else:
            response = request(prompts, base_url=base_url, api_key=api_key, model=model, model_name=model_name)["choices"][0]["message"]["content"]
    except Exception as e:
        response = {"error": str(e)}
        print ("Images:", images)
    
    return response


def process_prompt(data, model_components):
    if data['type'] == 'Standard(4opts)':
        prompt = mmmu_doc_to_text(data)
        images = origin_mmmu_doc_to_visual(data)
    elif data['type'] == 'Standard(10opts)':
        prompt = mmmu_doc_to_text(data)
        images = origin_mmmu_doc_to_visual(data)
    elif data['type'] == 'Vision':
        prompt = prompt_config['Vision']
        images = vision_mmmu_doc_to_visual(data)

    return infer({"prompt": prompt, "images": images}, max_tokens=4096, **model_components), data

def run_and_save():
    def save_results_to_file(results, output_path):
        with open(output_path, 'w', encoding='utf-8') as outfile:
            for output, data in results:
                data['response'] = output
                json.dump(data, outfile, ensure_ascii=False)
                outfile.write('\n')
    
    def retry_errors(results, model_components, part_name, output_path):
        retry_data = [(index, result, data) for index, (result, data) in enumerate(results) if isinstance(result, dict) and 'error' in result]
        no_change_count = 0
        previous_retry_count = len(retry_data)
        
        while retry_data:
            print(f"Retrying {len(retry_data)} failed prompts for {part_name}")
            new_results = []
            with ThreadPoolExecutor(max_workers=WORKERS) as executor:
                futures = [executor.submit(process_prompt, data, model_components) for _, _, data in retry_data]
                for future in tqdm(futures, desc=f"Retrying {part_name}"):
                    result, data = future.result()
                    new_results.append((result, data))

            # Update the results with the new results from the retry
            for (index, _, _), (new_result, new_data) in zip(retry_data, new_results):
                results[index] = (new_result, new_data)
            
            retry_data = [(index, result, data) for index, (result, data) in enumerate(results) if isinstance(result, dict) and 'error' in result]

            # Save results after each retry attempt
            save_results_to_file(results, output_path)

            # Check for no change in the number of retries
            if len(retry_data) == previous_retry_count:
                no_change_count += 1
            else:
                no_change_count = 0
            
            if no_change_count >= 3:
                print(f"No change in retry count for 3 consecutive attempts. Exiting retry loop for {part_name}.")
                break

            previous_retry_count = len(retry_data)
        
        return results

    dataset = []
    with open("./mix_data.jsonl", 'r', encoding='utf-8') as infile:
        for i, data in enumerate(infile):
            if i >= NUM:
                break
            item = json.loads(data)
            item['type'] = 'Standard(4opts)'
            item['prompt_mode'] = MODE
            dataset.append(item)
    with open("./mix_data.jsonl", 'r', encoding='utf-8') as infile:
        for i, data in enumerate(infile):
            if i >= NUM:
                break
            item = json.loads(data)
            item['type'] = 'Standard(10opts)'
            item['prompt_mode'] = MODE
            dataset.append(item)

    with open("./mix_data.jsonl", 'r', encoding='utf-8') as infile:
        for i, data in enumerate(infile):
            if i >= NUM:
                break
            item = json.loads(data)
            item['type'] = 'Vision'
            item['prompt_mode'] = MODE
            dataset.append(item)

    model_components = load_model(model_name='GPT4O-MINI', base_url="https://api.openai.com/v1", api_key=API_KEY, model=MODEL)
    
    def process_and_save_part(part_data, part_name, model_components):
        print(f"Begin processing {part_name}")
        results = []
        output_path = f"./temp_output/{MODEL}_{MODE}_{part_name}.jsonl"

        if os.path.exists(output_path):
            with open(output_path, 'r', encoding='utf-8') as infile:
                for line in infile:
                    data = json.loads(line)
                    results.append((data['response'], data))
            print(f"Loaded existing results for {part_name}")
        else:
            with ThreadPoolExecutor(max_workers=WORKERS) as executor:
                futures = [executor.submit(process_prompt, data, model_components) for data in part_data]
                for future in tqdm(futures, desc=f"Processing {part_name}"):
                    result, data = future.result()
                    results.append((result, data))

            save_results_to_file(results, output_path)

        results = retry_errors(results, model_components, part_name, output_path)

        return output_path

    mmmu_data = [data for data in dataset if data['type'] == 'Standard(4opts)']
    origin_data = [data for data in dataset if data['type'] == 'Standard(10opts)']
    vision_data = [data for data in dataset if data['type'] == 'Vision']

    temp_files = []
    temp_files.append(process_and_save_part(mmmu_data, "Standard(4opts)", model_components))
    temp_files.append(process_and_save_part(origin_data, "Standard(10opts)", model_components))
    temp_files.append(process_and_save_part(vision_data, "Vision", model_components))



def main():
    run_and_save()


if __name__ == '__main__':  
    main()
