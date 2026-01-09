import json
import os
import re
from pathlib import Path
from typing import Tuple
import nbtlib
from nbtlib.tag import Compound, String, Int
import requests

TOKEN: str = os.getenv("API_TOKEN", "")
GH_TOKEN: str = os.getenv("GH_TOKEN", "")
PROJECT_ID: str = os.getenv("PROJECT_ID", "")
FILE_URL: str = f"https://paratranz.cn/api/projects/{PROJECT_ID}/files/"

if not TOKEN or not PROJECT_ID:
    raise EnvironmentError("环境变量 API_TOKEN 或 PROJECT_ID 未设置。")

# 初始化列表和字典
file_id_list: list[int] = []
file_path_list: list[str] = []
zh_cn_list: list[dict[str, str]] = []


def fetch_json(url: str, headers: dict[str, str]) -> list[dict[str, str]]:
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def translate(file_id: int) -> Tuple[list[str], list[str]]:
    """
    获取指定文件的翻译内容并返回键值对列表

    :param file_id: 文件ID
    :return: 包含键和值的元组列表
    """
    url = f"https://paratranz.cn/api/projects/{PROJECT_ID}/files/{file_id}/translation"
    headers = {"Authorization": TOKEN, "accept": "*/*"}
    translations = fetch_json(url, headers)

    keys, values = [], []

    for item in translations:
        keys.append(item["key"])
        translation = item.get("translation", "")
        original = item.get("original", "")
        # 优先使用翻译内容，缺失时根据 stage 使用原文
        values.append(
            original if item["stage"] in [0, -1, 2] or not translation else translation
        )

    return keys, values


def get_files() -> None:
    """
    获取项目中的文件列表并提取文件ID和路径
    """
    headers = {"Authorization": TOKEN, "accept": "*/*"}
    files = fetch_json(FILE_URL, headers)

    for file in files:
        file_id_list.append(file["id"])
        file_path_list.append(file["name"])


def save_translation(zh_cn_dict: dict[str, str], path: Path) -> None:
    """
    保存翻译内容到指定的 JSON 文件，并处理因Paratranz截断导致键不匹配的问题。

    :param zh_cn_dict: 从Paratranz获取的翻译内容的字典
    :param path: 原始文件路径
    """
    dir_path = Path("CNPack") / path.parent
    dir_path = Path(str(dir_path).replace("CNPack", "CNPack/assets/vm/lang"))
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / "zh_cn.json"
    source_path = str(file_path).replace("zh_cn.json", "en_us.json").replace("CNPack", "Source")

    with open(file_path, "w", encoding="UTF-8") as f:
        try:
            with open(source_path, "r", encoding="UTF-8") as f1:
                source_json: dict = json.load(f1)

            # --- 核心修复逻辑开始 ---

            # 1. 创建一个新字典，用于存放键已校正的翻译
            corrected_zh_cn_dict = {}
            unmatched_paratranz_keys = []

            for pt_key, pt_value in zh_cn_dict.items():
                # 2. 优先进行直接、完整的键匹配
                if pt_key in source_json:
                    corrected_zh_cn_dict[pt_key] = pt_value
                else:
                    # 3. 如果直接匹配失败，则认为该键可能被截断，暂存以进行下一步处理
                    unmatched_paratranz_keys.append(pt_key)
            
            # 4. 处理无法直接匹配的键（通常是被截断的键）
            source_keys_set = set(source_json.keys())
            for pt_key in unmatched_paratranz_keys:
                found_match = False
                # 检查键长度是否为255，这是被截断的强特征
                if len(pt_key) == 255:
                    for source_key in source_keys_set:
                        # 如果源键以被截断的键为前缀，则认为匹配成功
                        if source_key.startswith(pt_key):
                            corrected_zh_cn_dict[source_key] = zh_cn_dict[pt_key]
                            found_match = True
                            break # 找到匹配项，跳出内层循环
                
                if not found_match:
                    print(f"警告: Paratranz的键 '{pt_key[:50]}...' 在源文件中找不到匹配项，该翻译将被忽略。")

            # 5. 按照源文件(en_us.json)的键序，构建最终的json对象
            final_json_object = {}
            for source_key in source_json.keys():
                # 如果校正后的翻译字典中有这个键，则使用翻译；否则，保留原文作为备用
                final_json_object[source_key] = corrected_zh_cn_dict.get(source_key, source_json[source_key])
            
            # --- 核心修复逻辑结束 ---

            json.dump(final_json_object, f, ensure_ascii=False, indent=4, separators=(",", ":"))

        except IOError:
            print(f"源文件 {source_path} 路径不存在，文件将按Paratranz默认顺序排序！")
            # 在源文件不存在的情况下，无法进行键校正，只能按原样输出
            sorted_dict = {key: zh_cn_dict[key] for key in sorted(zh_cn_dict.keys())}
            json.dump(sorted_dict, f, ensure_ascii=False, indent=4, separators=(",", ":"))


def process_translation(file_id: int, path: Path) -> dict[str, str]:
    """
    处理单个文件的翻译，返回翻译字典

    :param file_id: 文件ID
    :param path: 文件路径
    :return: 翻译内容字典
    """
    keys, values = translate(file_id)

    # 尝试读取本地的 en_us.json 以保留原文格式
    try:
        with open("Source/" + str(path), "r", encoding="UTF-8") as f:
            zh_cn_dict = json.load(f)
    except IOError:
        zh_cn_dict = {}
        
    for key, value in zip(keys, values):
        # 确保替换 \\ 和 \n
        value = re.sub(r'\\\\', r'\\', value)
        value = re.sub(r'\\n', '\n', value)
        
        # 【核心修改】仅当值包含中文字符时，才将常规空格替换为不间断空格
        if re.search(r'[\u4e00-\u9fff]', value):
            value = re.sub(' ', '\u00A0', value)
            
        # 保存替换后的值
        zh_cn_dict[key] = value
        
    # 特殊处理：ftbquest 文件 (此部分逻辑在原脚本中似乎会被上面的循环结果覆盖，但为了保险起见一并修改)
    # 注意：原脚本的这部分逻辑会重新处理原始的 keys 和 values，覆盖上面的循环结果。
    # 因此，这里的修改至关重要。
    if "ftbquest" in path.name:
        zh_cn_dict = {
            # 【核心修改】在字典推导式中加入同样的中文判断逻辑
            key: value.replace(" ", "\u00A0") if "image" not in value and re.search(r'[\u4e00-\u9fff]', value) else value
            for key, value in zip(keys, values)
        }
    return zh_cn_dict


# Convert JSON data into an NBT compound structure
def json_to_nbt(data):
    if isinstance(data, dict):
        return Compound({key: json_to_nbt(value) for key, value in data.items()})
    elif isinstance(data, list):
        return nbtlib.tag.List[nbtlib.tag.String]([json_to_nbt(item) for item in data])
    elif isinstance(data, str):
        return String(data)
    elif isinstance(data, int):
        return Int(data)
    else:
        raise ValueError(f"Unsupported data type: {type(data)}")


# Pretty-print SNBT with indentation and wrap all values in double quotes
def format_snbt(nbt_data, indent=0):
    INDENT_SIZE = 4  # Number of spaces for each indent level
    indent_str = ' ' * indent

    if isinstance(nbt_data, Compound):
        formatted = ['{']
        for key, value in nbt_data.items():
            formatted.append(f'\n{indent_str}{" " * INDENT_SIZE}{key}:{format_snbt(value, indent + INDENT_SIZE)}')
        formatted.append(f'\n{indent_str}}}')
        return ''.join(formatted)

    elif isinstance(nbt_data, nbtlib.tag.List):
        formatted = ['[']
        for item in nbt_data:
            formatted.append(f'\n{indent_str}{" " * INDENT_SIZE}{format_snbt(item, indent + INDENT_SIZE)}')
        formatted.append(f'\n{indent_str}]')
        return ''.join(formatted)

    else:
        # Wrap all primitive types (String/Int) in double quotes
        return f'"{str(nbt_data)}"'


def escape_quotes(data):
    if isinstance(data, dict):
        return {key: escape_quotes(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [escape_quotes(item) for item in data]
    elif isinstance(data, str):
        return data.replace('"', '\\"')
    else:
        return data


def normal_json2_ftb_desc(origin_en_us):
    en_json = json.dumps(origin_en_us, ensure_ascii=False, indent=4, separators=(",", ":"))
    en_json = eval(en_json)
    temp_set = set()
    temp_en_json = {}
    for key, value in list(en_json.items()):
        if "desc" in key:
            key_id = key.split(".")[1]
            temp_json_array = []
            for k in en_json.keys():
                if f"{key_id}.quest_desc" in k:
                    temp_json_array.append(en_json[k])
            new_key = f"quest.{key_id}.quest_desc"
            temp_en_json[new_key] = temp_json_array
            temp_set.add(key)
    for key in temp_set:
        en_json.pop(key, None)
    en_json.update(temp_en_json)

    print("NormalJson2FtbDesc end...")
    return en_json


def main() -> None:
    get_files()
    ftbquests_dict = {}
    for file_id, path in zip(file_id_list, file_path_list):
        # 优化：只处理以 en_us.json 结尾的文件，并跳过包含 TM 的文件
        if not path.lower().endswith("en_us.json") or "TM" in path:
            continue

        zh_cn_dict = process_translation(file_id, Path(path))
        zh_cn_list.append(zh_cn_dict)

        # 收集 FTB Quests 的翻译以便后续生成 SNBT
        if "kubejs/assets/quests/lang/" in path:
            ftbquests_dict = ftbquests_dict | zh_cn_dict

        save_translation(zh_cn_dict, Path(path))
        print(f"已从Patatranz下载到仓库：{re.sub('en_us.json', 'zh_cn.json', path)}")
    if(len(ftbquests_dict) > 0):
        snbt_dict = normal_json2_ftb_desc(ftbquests_dict)
        # json_data = json.dumps(snbt_dict,ensure_ascii=False, indent=4, separators=(",", ":"))
        # Escape quotation marks in the translated data
        json_data = escape_quotes(snbt_dict)
        # Convert the loaded JSON data to NBT format
        nbt_data = json_to_nbt(json_data)
        # Format the NBT structure as a pretty-printed SNBT string
        formatted_snbt_string = format_snbt(nbt_data)
        # Optionally save the formatted SNBT to a file
        try:
            with open('CNPack/config/ftbquests/quests/lang/zh_cn.snbt', 'w', encoding='utf-8') as snbt_file:
                snbt_file.write(formatted_snbt_string)
        except Exception as e:
            print("该ftbquest版本低于1.21.1")

if __name__ == "__main__":
    main()
