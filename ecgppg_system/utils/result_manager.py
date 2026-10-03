import os
import json
from datetime import datetime
from typing import Dict, List, Any
from ..utils.logger import setup_logger
from ..config import settings

logger = setup_logger(__name__)

class ResultManager:
    """结果管理器类，处理结果保存和加载"""
    
    @staticmethod
    def save_results(results: Dict[str, Any], signal_types: List[str], prefix: str = "results") -> str:
        """
        保存认证和训练结果
        
        Args:
            results: 结果字典
            signal_types: 处理的信号类型列表
            prefix: 结果文件名前缀
            
        Returns:
            str: 保存的文件路径
        """
        # 创建时间戳
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 确保输出目录存在
        if not os.path.exists(settings.OUTPUT_DIR):
            os.makedirs(settings.OUTPUT_DIR)
        
        # 创建结果文件路径
        result_file = os.path.join(settings.OUTPUT_DIR, f"{prefix}_{timestamp}.txt")
        result_json = os.path.join(settings.OUTPUT_DIR, f"{prefix}_{timestamp}.json")
        
        try:
            # 保存文本结果
            with open(result_file, 'w', encoding='utf-8') as f:
                # 写入标题
                f.write("=" * 80 + "\n")
                f.write(" " * 25 + "生物特征身份验证系统结果\n")
                f.write("=" * 80 + "\n")
                f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("-" * 80 + "\n\n")
                
                # 根据结果类型写入内容
                if "fusion_authentication" in results:
                    # 写入融合结果
                    ResultManager._write_fusion_results(f, results["fusion_authentication"])
                else:
                    # 写入单信号结果
                    for signal_type in signal_types:
                        ResultManager._write_single_signal_results(f, signal_type, results)
                        
            # 保存JSON结果 (过滤掉不可序列化的内容)
            serializable_results = ResultManager._prepare_for_serialization(results)
            with open(result_json, 'w', encoding='utf-8') as f:
                json.dump(serializable_results, f, indent=2, ensure_ascii=False)
                
            logger.info(f"结果已保存到: {result_file}")
            logger.info(f"JSON结果已保存到: {result_json}")
            return result_file
            
        except Exception as e:
            logger.exception(f"保存结果时出错: {str(e)}")
            return ""
    
    @staticmethod
    def load_results(result_file: str) -> Dict[str, Any]:
        """
        加载已保存的结果
        
        Args:
            result_file: 结果文件路径 (JSON格式)
            
        Returns:
            Dict: 加载的结果
        """
        try:
            if not os.path.exists(result_file):
                logger.error(f"结果文件不存在: {result_file}")
                return {}
                
            with open(result_file, 'r', encoding='utf-8') as f:
                results = json.load(f)
                
            logger.info(f"成功加载结果: {result_file}")
            return results
            
        except Exception as e:
            logger.exception(f"加载结果时出错: {str(e)}")
            return {}
    
    @staticmethod
    def _write_fusion_results(file, fusion_result: Dict[str, Any]) -> None:
        """
        写入融合认证结果
        
        Args:
            file: 打开的文件对象
            fusion_result: 融合认证结果
        """
        file.write("\n双信号融合认证结果:\n")
        file.write("-" * 40 + "\n")
        
        # 写入融合结果
        file.write(f"  认证状态: {'成功' if fusion_result.get('success', False) else '失败'}\n")
        file.write(f"  融合相似度: {fusion_result.get('similarity', 0):.2f}%\n")
        file.write(f"  融合阈值: {fusion_result.get('threshold', 0):.2f}%\n\n")
        
        # ECG子结果
        ecg_result = fusion_result.get("ecg_result", {})
        file.write("  ECG结果:\n")
        file.write(f"    相似度: {ecg_result.get('similarity', 0):.2f}%\n")
        file.write(f"    阈值: {ecg_result.get('threshold', 0):.2f}%\n")
        file.write(f"    状态: {'成功' if ecg_result.get('success', False) else '失败'}\n\n")
        
        # PPG子结果
        ppg_result = fusion_result.get("ppg_result", {})
        file.write("  PPG结果:\n")
        file.write(f"    相似度: {ppg_result.get('similarity', 0):.2f}%\n")
        file.write(f"    阈值: {ppg_result.get('threshold', 0):.2f}%\n")
        file.write(f"    状态: {'成功' if ppg_result.get('success', False) else '失败'}\n\n")
    
    @staticmethod
    def _write_single_signal_results(file, signal_type: str, results: Dict[str, Any]) -> None:
        """
        写入单一信号结果
        
        Args:
            file: 打开的文件对象
            signal_type: 信号类型
            results: 所有结果的字典
        """
        file.write(f"\n{signal_type.upper()}处理结果:\n")
        file.write("-" * 40 + "\n")
        
        # 写入认证结果
        auth_key = f"{signal_type}_authentication"
        if auth_key in results:
            file.write("\n身份认证结果:\n")
            auth_result = results[auth_key]
            file.write(f"  认证状态: {'成功' if auth_result.get('success', False) else '失败'}\n")
            file.write(f"  相似度: {auth_result.get('similarity', 0):.2f}%\n")
            file.write(f"  阈值: {auth_result.get('threshold', 0):.2f}%\n")
            
            # 如果有基础认证和模型认证分量
            if "auth_similarity" in auth_result and "model_similarity" in auth_result:
                file.write(f"  基础认证相似度: {auth_result.get('auth_similarity', 0):.2f}%\n")
                file.write(f"  模型认证相似度: {auth_result.get('model_similarity', 0):.2f}%\n")
        
        # 写入模型训练结果
        model_key = f"{signal_type}_model"
        if model_key in results:
            model_result = results[model_key]
            if "history" in model_result and model_result["history"]:
                history = model_result["history"]
                file.write("\n模型训练结果:\n")
                if "final_loss" in history:
                    file.write(f"  最终损失: {history.get('final_loss', 0):.6f}\n")
                if "final_accuracy" in history:
                    file.write(f"  最终准确率: {history.get('final_accuracy', 0):.4f}\n")
                if "epochs_trained" in history:
                    file.write(f"  训练轮数: {history.get('epochs_trained', 0)}\n")
        
        # 写入预测结果
        prediction_key = f"{signal_type}_prediction"
        if prediction_key in results:
            file.write("\n预测结果:\n")
            file.write(f"  预测步数: {len(results[prediction_key].get('predicted', []))}\n")
        
        file.write("\n")
    
    @staticmethod
    def _prepare_for_serialization(results: Dict[str, Any]) -> Dict[str, Any]:
        """
        准备结果用于序列化 (移除不可JSON序列化的内容)
        
        Args:
            results: 原始结果字典
            
        Returns:
            Dict: 可序列化的结果字典
        """
        serializable = {}
        
        for key, value in results.items():
            if isinstance(value, dict):
                # 递归处理嵌套字典
                if "model" in value:
                    # 跳过模型对象
                    filtered_value = {k: v for k, v in value.items() if k != "model"}
                    serializable[key] = ResultManager._prepare_for_serialization(filtered_value)
                else:
                    serializable[key] = ResultManager._prepare_for_serialization(value)
            elif isinstance(value, (str, int, float, bool, list)) or value is None:
                # 基本类型可以直接序列化
                serializable[key] = value
            elif hasattr(value, "tolist") and callable(getattr(value, "tolist")):
                # 转换numpy数组
                try:
                    serializable[key] = value.tolist()
                except:
                    # 如果转换失败，跳过
                    pass
            else:
                # 其他类型忽略
                pass
        
        return serializable 