"""
模型IO模块

提供模型加载和保存的功能。

这里存的是**部署模型**（用于身份比对）：元数据收在 `metadata` 键下，
`load_model` 返回 `(model, metadata)`。另有一套面向**训练检查点**的格式在
`ecgppg_system/utils/model_utils.py`，两者互不相通，详见那边的模块说明。
"""

import copy
import os
import numpy as np
import torch
import torch.nn as nn
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

from ecgppg_system.models.bilstm import BiLSTMWithAttention
from ecgppg_system.utils.logger import logger
from ecgppg_system.config import settings
from ecgppg_system.devices.device_manager import EnvironmentManager

#: 重建网络时的默认结构参数。
#:
#: 必须与 `model_creator.create_model` 的默认值保持一致 —— 只会用在**旧存档**上
#: （它的 metadata 里只有 input_size）。新存档会把自己的结构写进 model_config，
#: 不再依赖这里的数字。
_DEFAULT_ARCHITECTURE = {
    'hidden_size': 64,
    'num_layers': 2,
    'output_size': 1,
    'dropout': 0.1,
    'bidirectional': True,
}


def _model_attr(model: nn.Module, key: str):
    """
    读模型的结构参数，抹平属性名差异。

    注意 `dropout`：在 nn.Module 上这个名字是 **Dropout 层对象本身**，比率存在
    `dropout_rate` 里。若直接 `getattr(model, 'dropout')` 就会把整个层写进
    metadata —— 存档从此不再"只含张量与基础类型"，`weights_only=True` 直接拒绝加载。

    取不到时返回 None，由调用方决定是否写进存档 —— 不用默认值填充，
    否则会把"没读到"伪装成"确实是 64"。
    """
    if key == 'dropout':
        value = getattr(model, 'dropout_rate', None)
        if value is None:
            candidate = getattr(model, 'dropout', None)
            value = candidate if isinstance(candidate, (int, float)) else None
        return float(value) if isinstance(value, (int, float)) else None

    value = getattr(model, key, None)
    if value is None and key == 'input_size':
        lstm = getattr(model, 'lstm', None)
        if lstm is not None:
            value = getattr(lstm, 'input_size', None)
    return value


def _as_template_tensor(template):
    """
    把注册模板整理成 ``[窗口数, 窗口长度]`` 的 float32 张量。

    只接受二维输入：模板的语义就是「若干条等长窗口」。一维数组通常是被误传的
    整段信号 —— 存进去也能读出来，但后续逐窗比对会拿着形状不对的东西静默算错，
    所以这里直接拒收并留日志，而不是尽力猜它想表达什么。

    返回 None 表示「这份存档不带模板」，与「模板是空数组」是同一件事：
    两者都不该让保存失败，只是失去「与注册样本比对」这一能力。
    """
    if template is None:
        return None
    try:
        if torch.is_tensor(template):
            array = template.detach().cpu().numpy()
        else:
            array = np.asarray(template)
    except Exception as exc:
        logger.warning("模板无法转换为数组，跳过保存: %s", exc)
        return None

    if array.ndim != 2:
        logger.warning(
            "模板应为二维 [窗口数, 窗口长度]，实际形状为 %s，跳过保存", array.shape,
        )
        return None
    if array.size == 0:
        logger.warning("模板为空，跳过保存")
        return None
    if not np.all(np.isfinite(array)):
        logger.warning("模板包含非有限值（NaN/Inf），跳过保存")
        return None

    return torch.as_tensor(np.ascontiguousarray(array), dtype=torch.float32)


def save_model(model: nn.Module, save_path: str, metadata: Dict[str, Any] = None,
               template=None) -> bool:
    """
    保存模型和相关元数据
    
    Args:
        model: 要保存的模型
        save_path: 保存路径
        metadata: 要保存的元数据
        template: 注册时用于训练的窗口矩阵 ``[窗口数, 窗口长度]``。
            与模型存在**同一个文件**里，而不是另开一个文件：
            另存会让「删模型」与「删模板」变成两件必须同时记得的事，
            也会多出一处需要防路径越界的写入点。存成同级的张量键，
            生命周期天然一致，且 ``weights_only=True`` 照样能读。
        
    Returns:
        bool: 是否成功保存
    """
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        
        # 准备保存数据。
        # deepcopy：下面要往 metadata 里补字段，不能改到调用方持有的那个字典。
        save_dict = {
            'model_state_dict': model.state_dict(),
            'save_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'metadata': copy.deepcopy(metadata or {}),
        }

        # 注册模板：只放张量，不放 metadata —— metadata 必须保持「只含基础类型」，
        # 否则 weights_only=True 会拒绝加载整份存档。
        template_tensor = _as_template_tensor(template)
        if template_tensor is not None:
            save_dict['template_windows'] = template_tensor
            # 在 metadata 里留一份形状摘要：不读张量也能知道这份存档带模板、
            # 窗口长度是多少，便于排查「按错误的窗口长度去比对」。
            save_dict['metadata']['template'] = {
                'windows': int(template_tensor.shape[0]),
                'window_length': int(template_tensor.shape[1]),
            }
        else:
            save_dict['metadata'].setdefault('template', None)

        # 顶层 input_size 是旧格式的兼容字段，load_model 仍会先读它
        if 'input_size' not in save_dict['metadata']:
            input_size = _model_attr(model, 'input_size')
            if input_size is not None:
                save_dict['metadata']['input_size'] = input_size

        # 完整结构参数：旧存档只有 input_size，重建时只能靠硬编码的 64/2/1；
        # 新存档把 hidden_size / num_layers / output_size / dropout / bidirectional
        # 一并写进去，将来改默认结构也不会让已有模型加载失败。
        # 调用方已给的值优先 —— 它们来自训练时的实际配置，比属性探测更权威。
        model_config = save_dict['metadata'].setdefault('model_config', {})
        for key in ('input_size', 'hidden_size', 'num_layers', 'output_size',
                    'dropout', 'bidirectional'):
            if key in model_config:
                continue
            value = _model_attr(model, key)
            # 只收基础类型：元数据里一旦混进 module / tensor，存档就不再能被
            # weights_only=True 读取（那正是加载侧刻意锁定的安全默认值）。
            if isinstance(value, (int, float, bool, str)):
                model_config[key] = value
            elif value is not None:
                logger.warning(
                    "忽略无法存档的结构参数 %s=%r（只接受基础类型）", key, value,
                )

        # 保存模型
        torch.save(save_dict, save_path)
        logger.info(f"模型已保存到: {save_path}")
        return True
    except Exception as e:
        logger.error(f"保存模型失败: {str(e)}")
        return False

def load_model(model_path: str, device: torch.device = None) -> Tuple[nn.Module, Dict[str, Any]]:
    """
    加载模型和相关元数据
    
    Args:
        model_path: 模型路径
        device: 计算设备，如果为None则使用最优设备
        
    Returns:
        tuple: (model, metadata)
    """
    try:
        # 确定设备
        if device is None:
            device = EnvironmentManager.get_optimal_device()
        
        logger.info(f"尝试加载模型: {model_path}")
        
        # 加载检查点
        # 显式声明 weights_only=True：只反序列化张量与基础类型，不执行任意 pickle 对象。
        # torch>=2.6 已默认如此，这里写出来是为了锁定行为 ——
        # model_path 来自数据库，若将来迁移模型库或降级依赖导致默认值变化，
        # 就会变成反序列化代码执行的风险。
        checkpoint = torch.load(model_path, map_location=device, weights_only=True)
        
        # 提取元数据（原先这里连着赋值两次，第一次是多余的）
        metadata = checkpoint.get('metadata', {})
        if not isinstance(metadata, dict):
            metadata = {}
        state_dict = checkpoint['model_state_dict']

        # 结构参数优先读新格式的 model_config，其次回退到旧格式的顶层 input_size。
        # 缺 input_size 时不要硬着头皮建网络：nn.LSTM(input_size=None) 抛出的
        # TypeError 与真正原因无关，只会把"存档缺字段"报成"加载失败"。
        model_config = metadata.get('model_config') or {}
        if not isinstance(model_config, dict):
            model_config = {}

        input_size = model_config.get('input_size', metadata.get('input_size'))
        try:
            input_size = int(input_size)
        except (TypeError, ValueError):
            logger.error(
                "模型缺少可用的 input_size 元数据(%r)，无法重建网络结构: %s",
                input_size, model_path,
            )
            return None, None

        architecture = {}
        for key, default in _DEFAULT_ARCHITECTURE.items():
            value = model_config.get(key, default)
            try:
                if isinstance(default, bool):
                    # 存档经过 YAML/JSON 中转时可能是 "false" 字符串
                    if isinstance(value, str):
                        value = value.strip().lower() in ('1', 'true', 'yes', 'on')
                    architecture[key] = bool(value)
                else:
                    architecture[key] = type(default)(value)
            except (TypeError, ValueError):
                logger.warning(
                    "模型元数据 %s=%r 非法，回退到默认值 %r: %s",
                    key, value, default, model_path,
                )
                architecture[key] = default

        # 创建模型：结构来自存档，而不是写死的 64/2/1
        model = BiLSTMWithAttention(input_size=input_size, **architecture)

        # 加载权重：形状不匹配时把"期望的结构"一起写进日志，便于判断是存档
        # 结构参数错了还是权重来自另一套模型。
        try:
            model.load_state_dict(state_dict)
        except RuntimeError as exc:
            logger.error(
                "模型权重与重建的网络结构不匹配（input_size=%s, %s）: %s",
                input_size, architecture, exc,
            )
            return None, None
        
        # 移动模型到指定设备
        model.to(device)

        # 部署模型默认就是推理态：留在 train() 会让 Dropout 继续生效，
        # 同一条输入两次调用可能得到不同分数（判定因此不可复现）。
        # 需要继续训练的调用方自己调 model.train() 即可覆盖。
        model.eval()

        logger.info(f"成功加载模型: input_size={input_size}")
        return model, metadata
        
    except Exception as e:
        logger.error(f"加载模型失败: {str(e)}")
        return None, None

def load_template(model_path: str) -> Optional[np.ndarray]:
    """
    读取某个模型存档附带的注册模板（若干等长窗口）。

    只读一个键，**不重建网络也不加载权重** —— 与模板比对时模型并不参与，
    没必要为此付一次结构重建的开销。

    Args:
        model_path: 模型路径

    Returns:
        ``[窗口数, 窗口长度]`` 的 float64 数组；存档里没有模板（旧存档、
        或注册时没传）时返回 None。文件读不出来同样返回 None —— 调用方
        据此降级为「只按模型分数判定」，而不是让整次认证失败。
    """
    try:
        # 与 load_model 同一口径：锁死 weights_only，模板是纯数值张量，
        # 不需要放宽反序列化范围。
        checkpoint = torch.load(model_path, map_location='cpu', weights_only=True)
    except Exception as exc:
        logger.error("读取注册模板失败: %s", exc)
        return None

    if not isinstance(checkpoint, dict):
        return None

    stored = checkpoint.get('template_windows')
    if stored is None:
        return None

    array = stored.detach().cpu().numpy() if torch.is_tensor(stored) else np.asarray(stored)
    if array.ndim != 2 or array.size == 0:
        logger.warning("存档中的模板形状异常(%s)，按「无模板」处理", getattr(array, 'shape', None))
        return None
    if not np.all(np.isfinite(array)):
        logger.warning("存档中的模板包含非有限值，按「无模板」处理")
        return None

    return array.astype(np.float64, copy=False)


def extract_model_metadata(checkpoint: Dict[str, Any]) -> Dict[str, Any]:
    """
    提取模型元数据
    
    Args:
        checkpoint: 模型检查点字典
        
    Returns:
        dict: 元数据字典
    """
    metadata = {}
    
    # 检查是否是新格式（带元数据的字典）
    if isinstance(checkpoint, dict):
        # 直接提取元数据
        if 'metadata' in checkpoint:
            metadata = checkpoint['metadata']
        
        # 提取保存时间
        if 'save_time' in checkpoint:
            metadata['save_time'] = checkpoint['save_time']
            
    return metadata

def verify_model_compatibility(model: nn.Module, 
                              expected_input_size: int = None,
                              expected_output_size: int = None) -> Tuple[bool, str]:
    """
    验证模型与当前环境的兼容性
    
    Args:
        model: 模型实例
        expected_input_size: 期望的输入大小
        expected_output_size: 期望的输出大小
        
    Returns:
        Tuple[bool, str]: (是否兼容, 不兼容原因)
    """
    # 验证输入大小
    actual_input_size = None
    if hasattr(model, 'input_size'):
        actual_input_size = model.input_size
    elif hasattr(model, 'lstm') and hasattr(model.lstm, 'input_size'):
        actual_input_size = model.lstm.input_size
    
    if expected_input_size is not None and actual_input_size != expected_input_size:
        return False, f"输入大小不匹配: 期望 {expected_input_size}, 实际 {actual_input_size}"
    
    # 验证输出大小
    actual_output_size = None
    if hasattr(model, 'output_size'):
        actual_output_size = model.output_size
    elif hasattr(model, 'fc') and hasattr(model.fc, 'out_features'):
        actual_output_size = model.fc.out_features
    
    if expected_output_size is not None and actual_output_size != expected_output_size:
        return False, f"输出大小不匹配: 期望 {expected_output_size}, 实际 {actual_output_size}"
    
    return True, ""

def get_automatic_save_path(signal_type: str) -> str:
    """
    根据信号类型和当前时间自动生成保存路径
    
    Args:
        signal_type: 信号类型
        
    Returns:
        str: 保存路径
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{signal_type}_{timestamp}_model.pth"
    return os.path.join(settings.MODEL_DIR, filename) 