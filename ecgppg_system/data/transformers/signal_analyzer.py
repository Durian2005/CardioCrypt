"""
信号分析模块
提供信号周期、峰值检测和特征提取功能
"""

import numpy as np
from scipy.signal import find_peaks
import matplotlib.pyplot as plt
from typing import List, Dict, Tuple, Union, Optional
from ...utils.logger import logger
from ...utils.matplotlib_setup import configure_matplotlib

# 配置matplotlib
configure_matplotlib()

class SignalAnalyzer:
    """信号分析器类，提供信号特征分析功能"""
    
    def __init__(self, signal_type: str = 'ecg'):
        """
        初始化信号分析器
        
        参数:
            signal_type: 信号类型 ('ecg' 或 'ppg')
        """
        self.signal_type = signal_type.lower()
        self._peak_detection_params = self._get_default_peak_params()
        logger.info(f"初始化{self.signal_type.upper()}信号分析器")
    
    def _get_default_peak_params(self) -> Dict:
        """获取默认的峰值检测参数"""
        if self.signal_type == 'ecg':
            return {
                'height': None,          # 峰值最小高度
                'threshold': None,       # 峰值最小阈值
                'distance': 50,          # 峰值间最小距离
                'prominence': 0.1,       # 峰值最小凸度
                'width': None,           # 峰值最小宽度
                'wlen': None,            # 用于计算凸度的窗口长度
                'rel_height': 0.5,       # 用于宽度计算的相对高度
                'plateau_size': None     # 平顶峰值大小范围
            }
        else:  # ppg
            return {
                'height': None,
                'threshold': None,
                'distance': 100,         # PPG峰值通常更宽
                'prominence': 0.05,
                'width': None,
                'wlen': None,
                'rel_height': 0.5,
                'plateau_size': None
            }
    
    def set_peak_detection_params(self, **params) -> None:
        """
        设置峰值检测参数
        
        参数:
            **params: 峰值检测参数，参见scipy.signal.find_peaks
        """
        # 更新参数
        for key, value in params.items():
            if key in self._peak_detection_params:
                self._peak_detection_params[key] = value
            else:
                logger.warning(f"未知的峰值检测参数: {key}")
        
        logger.info(f"已更新峰值检测参数: {self._peak_detection_params}")
    
    def detect_peaks(self, signal: np.ndarray, 
                     return_properties: bool = False) -> Union[np.ndarray, Tuple]:
        """
        检测信号中的峰值
        
        参数:
            signal: 信号数据
            return_properties: 是否返回峰值属性
            
        返回:
            np.ndarray 或 Tuple: 峰值索引，如果return_properties为True，则还返回峰值属性
        """
        # 确保信号是一维数组
        signal = np.asarray(signal).flatten()
        
        # 使用scipy.signal.find_peaks检测峰值
        peaks, properties = find_peaks(
            signal,
            height=self._peak_detection_params['height'],
            threshold=self._peak_detection_params['threshold'],
            distance=self._peak_detection_params['distance'],
            prominence=self._peak_detection_params['prominence'],
            width=self._peak_detection_params['width'],
            wlen=self._peak_detection_params['wlen'],
            rel_height=self._peak_detection_params['rel_height'],
            plateau_size=self._peak_detection_params['plateau_size']
        )
        
        logger.info(f"检测到{len(peaks)}个峰值")
        
        if return_properties:
            return peaks, properties
        else:
            return peaks
    
    def detect_troughs(self, signal: np.ndarray, 
                       return_properties: bool = False) -> Union[np.ndarray, Tuple]:
        """
        检测信号中的谷值
        
        参数:
            signal: 信号数据
            return_properties: 是否返回谷值属性
            
        返回:
            np.ndarray 或 Tuple: 谷值索引，如果return_properties为True，则还返回谷值属性
        """
        # 通过对信号取反来检测谷值
        inverted_signal = -signal
        troughs, properties = find_peaks(
            inverted_signal,
            height=self._peak_detection_params['height'],
            threshold=self._peak_detection_params['threshold'],
            distance=self._peak_detection_params['distance'],
            prominence=self._peak_detection_params['prominence'],
            width=self._peak_detection_params['width'],
            wlen=self._peak_detection_params['wlen'],
            rel_height=self._peak_detection_params['rel_height'],
            plateau_size=self._peak_detection_params['plateau_size']
        )
        
        logger.info(f"检测到{len(troughs)}个谷值")
        
        if return_properties:
            return troughs, properties
        else:
            return troughs
    
    def find_period(self, signal: np.ndarray, method: str = 'peaks') -> int:
        """
        检测信号周期
        
        参数:
            signal: 信号数据
            method: 检测方法 ('peaks', 'autocorr', 'fft')
            
        返回:
            int: 检测到的周期长度（数据点数）
        """
        # 确保信号是一维数组
        signal = np.asarray(signal).flatten()
        
        if method == 'peaks':
            # 使用峰值检测方法
            peaks = self.detect_peaks(signal)
            
            if len(peaks) < 2:
                logger.warning("检测到的峰值不足两个，无法确定周期")
                return self._get_default_period()
            
            # 计算相邻峰值间的距离
            peak_diffs = np.diff(peaks)
            
            # 计算周期为峰值间隔的中位数
            period = int(np.median(peak_diffs))
            
        elif method == 'autocorr':
            # 使用自相关函数检测周期
            max_lag = min(5000, len(signal) // 2)
            autocorr = np.correlate(signal, signal, mode='full')
            autocorr = autocorr[len(signal)-1:len(signal)-1+max_lag]
            
            # 找到自相关函数的峰值
            peaks, _ = find_peaks(autocorr, distance=20)
            
            if len(peaks) < 1:
                logger.warning("自相关函数中未检测到峰值，无法确定周期")
                return self._get_default_period()
                
            # 第一个峰值通常对应于周期
            period = peaks[0]
            
        elif method == 'fft':
            # 使用FFT检测周期
            from scipy.fftpack import fft
            
            # 计算FFT
            n = len(signal)
            fft_result = fft(signal)
            
            # 获取频率域
            freqs = np.fft.fftfreq(n)
            
            # 找到主频率（排除直流分量）
            idx = np.argmax(np.abs(fft_result[1:n//2])) + 1
            freq = freqs[idx]
            
            # 周期是频率的倒数
            period = int(1.0 / np.abs(freq))
            
        else:
            logger.warning(f"未知的周期检测方法: {method}")
            return self._get_default_period()
        
        # 对周期进行合理性检查
        if self.signal_type == 'ecg':
            if period < 50 or period > 300:
                logger.warning(f"检测到的ECG周期 ({period}) 不在合理范围内")
                return self._get_default_period()
        else:  # ppg
            if period < 100 or period > 400:
                logger.warning(f"检测到的PPG周期 ({period}) 不在合理范围内")
                return self._get_default_period()
                
        logger.info(f"检测到的信号周期长度: {period}个采样点")
        return period
    
    def _get_default_period(self) -> int:
        """获取默认周期长度"""
        if self.signal_type == 'ecg':
            return 200  # 约1秒（对于200Hz采样率）
        else:  # ppg
            return 250  # 约1.25秒
    
    def extract_periods(self, signal: np.ndarray, period_length: Optional[int] = None) -> List[np.ndarray]:
        """
        提取信号周期
        
        参数:
            signal: 信号数据
            period_length: 周期长度（数据点数），如果为None则自动检测
            
        返回:
            List[np.ndarray]: 提取的周期列表
        """
        # 确保信号是一维数组
        signal = np.asarray(signal).flatten()
        
        # 如果未指定周期长度，则自动检测
        if period_length is None:
            period_length = self.find_period(signal)
        
        # 从信号中提取完整周期
        periods = []
        for i in range(0, len(signal) - period_length, period_length):
            periods.append(signal[i:i + period_length])
        
        logger.info(f"已提取{len(periods)}个完整周期，每个周期{period_length}个采样点")
        return periods
    
    def calculate_heart_rate(self, signal: np.ndarray, sampling_rate: float = 100.0) -> float:
        """
        计算心率
        
        参数:
            signal: 信号数据
            sampling_rate: 采样率（Hz）
            
        返回:
            float: 心率（BPM, 每分钟心跳次数）
        """
        # 使用峰值检测方法
        peaks = self.detect_peaks(signal)
        
        if len(peaks) < 2:
            logger.warning("检测到的峰值不足两个，无法计算心率")
            return 0.0
        
        # 计算相邻峰值间的平均距离（采样点数）
        peak_diffs = np.diff(peaks)
        avg_interval = np.mean(peak_diffs)
        
        # 将采样点转换为时间（秒）
        time_interval = avg_interval / sampling_rate
        
        # 计算心率（BPM）
        heart_rate = 60.0 / time_interval
        
        logger.info(f"计算得到的心率: {heart_rate:.1f} BPM")
        return heart_rate
    
    def detect_arrhythmia(self, signal: np.ndarray, sampling_rate: float = 100.0) -> Dict:
        """
        检测心律不齐
        
        参数:
            signal: 信号数据
            sampling_rate: 采样率（Hz）
            
        返回:
            Dict: 检测结果
        """
        if self.signal_type != 'ecg':
            logger.warning("心律不齐检测仅适用于ECG信号")
            return {"detected": False, "details": "非ECG信号"}
        
        # 检测R波峰值
        peaks = self.detect_peaks(signal)
        
        if len(peaks) < 5:
            logger.warning("检测到的峰值不足5个，无法进行心律不齐分析")
            return {"detected": False, "details": "数据不足"}
        
        # 计算RR间隔（毫秒）
        rr_intervals = np.diff(peaks) * (1000 / sampling_rate)
        
        # 计算RR间隔的标准差（SDNN）
        sdnn = np.std(rr_intervals)
        
        # 计算连续RR间隔差值的均方根（RMSSD）
        rmssd = np.sqrt(np.mean(np.square(np.diff(rr_intervals))))
        
        # 计算相邻RR间隔差值大于50ms的百分比（pNN50）
        nn50 = np.sum(np.abs(np.diff(rr_intervals)) > 50)
        pnn50 = (nn50 / len(rr_intervals)) * 100
        
        # 判断是否存在心律不齐
        # 这些阈值仅为示例，实际应用中应根据医学研究进行调整
        arrhythmia_detected = (sdnn > 100) or (rmssd > 50) or (pnn50 > 10)
        
        result = {
            "detected": arrhythmia_detected,
            "details": "检测到心律不齐" if arrhythmia_detected else "未检测到心律不齐",
            "metrics": {
                "SDNN": round(sdnn, 1),
                "RMSSD": round(rmssd, 1),
                "pNN50": round(pnn50, 1)
            }
        }
        
        logger.info(f"心律不齐分析结果: {result['details']} (SDNN={sdnn:.1f}, RMSSD={rmssd:.1f}, pNN50={pnn50:.1f}%)")
        return result
    
    def analyze_ppg_waveform(self, signal: np.ndarray) -> Dict:
        """
        分析PPG波形特征
        
        参数:
            signal: PPG信号数据
            
        返回:
            Dict: 分析结果
        """
        if self.signal_type != 'ppg':
            logger.warning("PPG波形分析仅适用于PPG信号")
            return {"success": False, "details": "非PPG信号"}
        
        # 检测峰值和谷值
        peaks = self.detect_peaks(signal)
        troughs = self.detect_troughs(signal)
        
        if len(peaks) < 2 or len(troughs) < 2:
            logger.warning("检测到的峰值或谷值不足，无法分析PPG波形")
            return {"success": False, "details": "峰值或谷值不足"}
        
        # 计算PPG特征
        features = {}
        
        # 1. 计算收缩期振幅
        #
        # 原注释写的是「收缩期和舒张期振幅」，但舒张期振幅从未实现（变量声明后
        # 一直没有被赋值）。这里把注释改成与代码一致，而不是补一个键上去：
        # PPG 的舒张期振幅按惯常定义指的是**重搏波**的高度，需要先定位重搏切迹
        # 的位置，而本方法后面只给出 `dicrotic_notch_present` 这个布尔结论、
        # 并没有定位切迹。硬凑一个「峰值到下个谷值的落差」既不标准，实测在该
        # 定义下也恒为 0 —— 那反而会让下游以为舒张期振幅真的是 0。
        systolic_amplitudes = []
        
        for i in range(min(len(peaks), len(troughs))):
            if peaks[i] > troughs[i]:
                # 确保峰值在谷值之后
                systolic_amplitudes.append(signal[peaks[i]] - signal[troughs[i]])
            else:
                # 谷值可能是下一个脉搏周期的开始
                if i < len(peaks) - 1:
                    systolic_amplitudes.append(signal[peaks[i]] - signal[troughs[i]])
        
        features["systolic_amplitude"] = np.mean(systolic_amplitudes) if systolic_amplitudes else 0
        
        # 2. 计算脉搏间隔
        pulse_intervals = np.diff(peaks)
        features["pulse_interval"] = np.mean(pulse_intervals) if len(pulse_intervals) > 0 else 0
        
        # 3. 检测二峰指数 (Dicrotic Notch)
        # 在收缩期峰值之后舒张期谷值之前寻找二峰
        dicrotic_notches = []
        
        for i in range(len(peaks) - 1):
            # 在当前峰值和下一个峰值之间查找二峰
            segment = signal[peaks[i]:peaks[i+1]]
            
            if len(segment) > 10:  # 确保有足够的点进行分析
                # 第一个峰值之后的局部最小值可能是二峰
                # 使用窗口大小为峰值间距离的1/3
                window_size = max(5, len(segment) // 3)
                
                for j in range(window_size, len(segment) - window_size):
                    if (segment[j] < segment[j-1] and segment[j] < segment[j+1] and
                        segment[j] < np.mean(segment[j-window_size:j]) and
                        segment[j] < np.mean(segment[j+1:j+window_size+1])):
                        dicrotic_notches.append(peaks[i] + j)
                        break
        
        features["dicrotic_notch_present"] = len(dicrotic_notches) > 0
        
        # 4. 计算上升时间和下降时间
        rise_times = []
        fall_times = []
        
        for i in range(min(len(peaks), len(troughs)) - 1):
            if troughs[i] < peaks[i] < troughs[i+1]:
                rise_times.append(peaks[i] - troughs[i])
                fall_times.append(troughs[i+1] - peaks[i])
        
        features["rise_time"] = np.mean(rise_times) if rise_times else 0
        features["fall_time"] = np.mean(fall_times) if fall_times else 0
        features["rise_fall_ratio"] = (features["rise_time"] / features["fall_time"] 
                                      if features["fall_time"] > 0 else 0)
        
        result = {
            "success": True,
            "features": features,
        }
        
        logger.info(f"PPG波形分析完成: 收缩期振幅={features['systolic_amplitude']:.2f}, "
                   f"脉搏间隔={features['pulse_interval']:.2f}, "
                   f"二峰存在={features['dicrotic_notch_present']}")
        
        return result
    
    def visualize_analysis(self, signal, analysis_type='peaks', figsize=(12, 8), save_path=None):
        """
        可视化分析结果
        
        参数:
            signal: 信号数据
            analysis_type: 分析类型 ('peaks', 'periods', 'features')
            figsize: 图表大小
            save_path: 保存路径
        """
        try:
            plt.figure(figsize=figsize)
            
            if analysis_type == 'peaks':
                # 检测峰值和谷值
                peaks = self.detect_peaks(signal)
                troughs = self.detect_troughs(signal)
                
                # 绘制信号
                plt.plot(signal, label='信号数据')
                
                # 标记峰值
                plt.plot(peaks, signal[peaks], 'ro', markersize=8, label='峰值')
                
                # 标记谷值
                plt.plot(troughs, signal[troughs], 'go', markersize=8, label='谷值')
                
                plt.title(f"{self.signal_type.upper()}信号峰值检测结果", fontsize=16)
                plt.xlabel("采样点", fontsize=14)
                plt.ylabel("信号幅度", fontsize=14)
                
            elif analysis_type == 'periods':
                # 找到周期
                period = self.find_period(signal)
                # 提取周期
                periods = self.extract_periods(signal, period)
                
                # 绘制原始信号
                plt.plot(signal, label='原始信号', alpha=0.5)
                
                # 绘制提取的周期
                colors = plt.cm.jet(np.linspace(0, 1, len(periods)))
                
                for i, p in enumerate(periods):
                    start = i * period
                    end = start + len(p)
                    if end <= len(signal):
                        plt.plot(range(start, end), p, color=colors[i], 
                                linewidth=2, alpha=0.8, label=f'周期 {i+1}' if i < 5 else "")
                
                plt.title(f"{self.signal_type.upper()}信号周期分析 (周期长度: {period}点)", fontsize=16)
                plt.xlabel("采样点", fontsize=14)
                plt.ylabel("信号幅度", fontsize=14)
                
            elif analysis_type == 'features':
                # 提取特征
                features = self.analyze_ppg_waveform(signal)["features"]
                
                # 绘制信号
                plt.plot(signal, label='信号数据')
                
                # 根据信号类型不同，标记不同的特征点
                if self.signal_type == 'ecg':
                    # 标记R波峰
                    if 'r_peaks' in features:
                        plt.plot(features['r_peaks'], signal[features['r_peaks']], 
                                'ro', markersize=8, label='R波峰')
                    
                    # 标记P波峰
                    if 'p_peaks' in features:
                        plt.plot(features['p_peaks'], signal[features['p_peaks']], 
                                'go', markersize=6, label='P波峰')
                    
                    # 标记T波峰
                    if 't_peaks' in features:
                        plt.plot(features['t_peaks'], signal[features['t_peaks']], 
                                'bo', markersize=6, label='T波峰')
                    
                    # 标记QRS起点
                    if 'qrs_onsets' in features:
                        plt.plot(features['qrs_onsets'], signal[features['qrs_onsets']], 
                                'mo', markersize=6, label='QRS起点')
                    
                    # 标记QRS终点
                    if 'qrs_offsets' in features:
                        plt.plot(features['qrs_offsets'], signal[features['qrs_offsets']], 
                                'co', markersize=6, label='QRS终点')
                    
                else:  # ppg
                    # 标记收缩峰
                    if 'systolic_peaks' in features:
                        plt.plot(features['systolic_peaks'], signal[features['systolic_peaks']], 
                                'ro', markersize=8, label='收缩峰')
                    
                    # 标记舒张谷
                    if 'diastolic_onsets' in features:
                        plt.plot(features['diastolic_onsets'], signal[features['diastolic_onsets']], 
                                'go', markersize=6, label='舒张起点')
                    
                    # 标记重搏波
                    if 'dicrotic_notches' in features:
                        plt.plot(features['dicrotic_notches'], signal[features['dicrotic_notches']], 
                                'bo', markersize=6, label='重搏波')
                    
                plt.title(f"{self.signal_type.upper()}信号特征检测结果", fontsize=16)
                plt.xlabel("采样点", fontsize=14)
                plt.ylabel("信号幅度", fontsize=14)
            
            plt.grid(True, alpha=0.3)
            plt.legend()
            plt.tight_layout()
            
            if save_path:
                plt.savefig(save_path, dpi=300, bbox_inches='tight')
                logger.info(f"分析图表已保存至: {save_path}")
            
            plt.show()
            
        except Exception as e:
            logger.error(f"可视化分析结果失败: {str(e)}")
    
    def split_by_custom_interval(self, signal: np.ndarray, 
                                  interval_length: int = 400,
                                  from_end: bool = True,
                                  max_intervals: int = 10) -> List[np.ndarray]:
        """
        按自定义区间长度分割信号
        
        参数:
            signal: 信号数据
            interval_length: 区间长度（数据点数）
            from_end: 是否从信号末尾开始分割
            max_intervals: 最大区间数量
            
        返回:
            List[np.ndarray]: 分割后的区间列表
        """
        # 确保信号是一维数组
        signal = np.asarray(signal).flatten()
        
        intervals = []
        total_length = min(len(signal), max_intervals * interval_length)
        
        if from_end:
            # 从末尾开始分割
            start = max(0, len(signal) - total_length)
            while start + interval_length <= len(signal):
                current_interval = signal[start:start + interval_length]
                intervals.append(current_interval)
                start += interval_length
        else:
            # 从开始处分割
            start = 0
            while start + interval_length <= len(signal) and len(intervals) < max_intervals:
                current_interval = signal[start:start + interval_length]
                intervals.append(current_interval)
                start += interval_length
        
        logger.info(f"按固定长度{interval_length}分割信号，获取{len(intervals)}个区间")
        return intervals
    
    def random_sample_intervals(self, signal: np.ndarray, 
                               interval_length: int = 400,
                               num_samples: int = 5,
                               non_overlapping: bool = True) -> List[np.ndarray]:
        """
        随机采样信号区间
        
        参数:
            signal: 信号数据
            interval_length: 区间长度（数据点数）
            num_samples: 采样数量
            non_overlapping: 是否禁止重叠
            
        返回:
            List[np.ndarray]: 采样的区间列表
        """
        # 确保信号是一维数组
        signal = np.asarray(signal).flatten()
        
        # 确保区间长度和采样数量合理
        if interval_length > len(signal):
            logger.warning(f"区间长度{interval_length}大于信号长度{len(signal)}，已调整")
            interval_length = len(signal)
            num_samples = 1
        
        # 计算合法的起始位置范围
        valid_starts = len(signal) - interval_length + 1
        
        # 如果区间不重叠，最多可以采样的数量是有限的
        if non_overlapping:
            max_possible = valid_starts // interval_length
            if num_samples > max_possible:
                logger.warning(f"请求的采样数{num_samples}超过最大可能值{max_possible}，已调整")
                num_samples = max_possible
        
        # 采样起始位置
        if non_overlapping:
            # 如果不允许重叠，等间距采样
            if num_samples > 1:
                step = valid_starts // num_samples
                start_positions = [i * step for i in range(num_samples)]
            else:
                start_positions = [0]
        else:
            # 如果允许重叠，随机采样
            start_positions = np.random.choice(valid_starts, size=num_samples, replace=False)
        
        # 提取区间
        intervals = []
        for start in start_positions:
            intervals.append(signal[start:start + interval_length])
        
        logger.info(f"随机采样{len(intervals)}个区间，每个长度{interval_length}")
        return intervals
    
    def find_peaks_with_filtering(self, signal: np.ndarray, 
                                 filter_noise: bool = True,
                                 filter_kwargs: dict = None) -> np.ndarray:
        """
        带预处理滤波的峰值检测
        
        参数:
            signal: 信号数据
            filter_noise: 是否先进行噪声滤波
            filter_kwargs: 滤波参数，默认使用中值滤波
            
        返回:
            np.ndarray: 峰值索引
        """
        # 确保信号是一维数组
        signal = np.asarray(signal).flatten()
        
        # 如果需要滤波
        if filter_noise:
            if filter_kwargs is None:
                filter_kwargs = {'window_length': 7, 'method': 'median'}
            
            # 使用滤波器预处理信号
            from scipy.signal import medfilt
            
            method = filter_kwargs.get('method', 'median')
            if method == 'median':
                window_length = filter_kwargs.get('window_length', 7)
                filtered_signal = medfilt(signal, kernel_size=window_length)
            else:
                # 默认中值滤波
                filtered_signal = medfilt(signal, kernel_size=7)
        else:
            filtered_signal = signal
        
        # 检测峰值
        peaks = self.detect_peaks(filtered_signal)
        
        logger.info(f"带滤波的峰值检测完成，检测到{len(peaks)}个峰值")
        return peaks
    
    def get_signal_quality(self, signal: np.ndarray) -> Dict:
        """
        评估信号质量
        
        参数:
            signal: 信号数据
            
        返回:
            Dict: 信号质量评估结果
        """
        # 确保信号是一维数组
        signal = np.asarray(signal).flatten()
        
        # 计算信号质量指标
        result = {}
        
        # 1. 信噪比估计（简化版）
        signal_power = np.var(signal)
        
        # 使用差分来估计噪声
        noise = np.diff(signal)
        noise_power = np.var(noise)
        
        if noise_power > 0:
            snr = 10 * np.log10(signal_power / noise_power)
        else:
            snr = 100  # 近似无噪声
        
        result['snr'] = round(snr, 2)
        
        # 2. 计算信号变异系数
        mean = np.mean(signal)
        std = np.std(signal)
        cv = std / mean if mean != 0 else float('inf')
        
        result['cv'] = round(cv, 4)
        
        # 3. 缺失值或异常值检测
        missing_values = np.sum(np.isnan(signal))
        result['missing_values'] = int(missing_values)
        
        # 4. 计算动态范围
        result['range'] = float(np.ptp(signal))
        
        # 5. 平滑度评估（高频成分比例）
        from scipy import fft
        fft_values = fft.fft(signal)
        fft_mag = np.abs(fft_values[:len(signal)//2])
        
        # 假设超过1/4频率的是高频
        high_freq_power = np.sum(fft_mag[len(fft_mag)//4:])
        total_power = np.sum(fft_mag)
        
        if total_power > 0:
            high_freq_ratio = high_freq_power / total_power
        else:
            high_freq_ratio = 0
            
        result['high_freq_ratio'] = round(high_freq_ratio, 4)
        
        # 6. 根据多个指标给出整体质量评分（0-100）
        # 这里使用简化的评分公式，实际应用可能需要更复杂的算法
        
        # SNR贡献
        snr_score = min(100, max(0, snr + 20)) / 120 * 40  # 最大贡献40分
        
        # CV贡献（越小越好，但不要太小）
        if cv < 0.001:  # 信号几乎是常数
            cv_score = 0
        elif cv > 2:  # 变异太大
            cv_score = 0
        else:
            cv_score = (1 - min(1, cv/2)) * 20  # 最大贡献20分
        
        # 高频成分贡献（越小越好）
        hf_score = (1 - high_freq_ratio) * 20  # 最大贡献20分
        
        # 缺失值贡献
        missing_score = (1 - min(1, missing_values/len(signal))) * 20  # 最大贡献20分
        
        # 总分
        quality_score = snr_score + cv_score + hf_score + missing_score
        
        # 质量分级
        if quality_score >= 80:
            quality_level = "优"
        elif quality_score >= 60:
            quality_level = "良"
        elif quality_score >= 40:
            quality_level = "中"
        else:
            quality_level = "差"
        
        result['quality_score'] = round(quality_score, 1)
        result['quality_level'] = quality_level
        
        logger.info(f"信号质量评估: 分数={result['quality_score']}分, 等级={result['quality_level']}")
        return result
    
    def compare_intervals(self, interval1: np.ndarray, interval2: np.ndarray,
                        use_dtw: bool = True) -> Dict:
        """
        比较两个信号区间的相似度
        
        参数:
            interval1: 第一个信号区间
            interval2: 第二个信号区间
            use_dtw: 是否使用DTW算法
            
        返回:
            Dict: 比较结果
        """
        # 确保输入是一维数组
        interval1 = np.asarray(interval1).flatten()
        interval2 = np.asarray(interval2).flatten()
        
        # 调整长度使两个区间匹配
        min_length = min(len(interval1), len(interval2))
        interval1 = interval1[:min_length]
        interval2 = interval2[:min_length]
        
        result = {}
        
        # 计算欧氏距离
        euclidean_dist = np.sqrt(np.sum((interval1 - interval2) ** 2))
        result['euclidean_distance'] = float(euclidean_dist)
        
        # 计算相关系数
        correlation = np.corrcoef(interval1, interval2)[0, 1]
        result['correlation'] = float(correlation)
        
        # 如果需要，使用DTW算法
        if use_dtw:
            try:
                from dtw import dtw
                alignment = dtw(interval1, interval2, keep_internals=True)
                dtw_distance = alignment.normalizedDistance
                result['dtw_distance'] = float(dtw_distance)
                
                # 转换为相似度分数
                dtw_similarity = 100 * (1 - min(1, dtw_distance/10))
                result['dtw_similarity'] = float(dtw_similarity)
            except ImportError:
                logger.warning("DTW库未安装，跳过DTW距离计算")
                dtw_similarity = 0
        
        # 计算综合相似度分数
        if use_dtw and 'dtw_similarity' in result:
            # 如果有DTW，主要基于DTW
            similarity = 0.7 * dtw_similarity + 0.3 * (max(0, correlation) * 100)
        else:
            # 否则基于相关系数和标准化欧氏距离
            norm_euclidean = min(1, euclidean_dist / (np.std(interval1) + np.std(interval2) + 1e-8))
            similarity = 0.6 * (max(0, correlation) * 100) + 0.4 * (100 * (1 - norm_euclidean))
        
        result['similarity_score'] = float(similarity)
        
        logger.info(f"区间比较完成: 相似度分数={result['similarity_score']:.1f}%")
        return result 