#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
字体工具模块
提供中文字体处理和修复相关的功能
"""

import os
import platform
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.font_manager import FontProperties
import numpy as np
from ..utils.logger import logger
import matplotlib.font_manager as fm
import warnings


# 默认中文字体文件路径
FONT_FILES = {
    'windows': {
        'msyh.ttc': 'C:/Windows/Fonts/msyh.ttc',        # 微软雅黑
        'msyhbd.ttc': 'C:/Windows/Fonts/msyhbd.ttc',    # 微软雅黑粗体
        'simhei.ttf': 'C:/Windows/Fonts/simhei.ttf',    # 黑体
        'simsun.ttc': 'C:/Windows/Fonts/simsun.ttc',    # 宋体
        'simfang.ttf': 'C:/Windows/Fonts/simfang.ttf',  # 仿宋
        'simkai.ttf': 'C:/Windows/Fonts/simkai.ttf',    # 楷体
    },
    'linux': {
        'wqy.ttc': '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        'noto.ttc': '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    },
    'darwin': {
        'pingfang.ttc': '/System/Library/Fonts/PingFang.ttc',
        'heiti.ttc': '/System/Library/Fonts/STHeiti Light.ttc',
    }
}

# 默认中文字体名称
FONT_NAMES = {
    'windows': ['Microsoft YaHei', 'SimSun', 'SimHei', 'FangSong', 'KaiTi'],
    'linux': ['WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'Droid Sans Fallback'],
    'darwin': ['PingFang SC', 'Heiti SC', 'Apple LiGothic', 'Hiragino Sans GB'],
}

def get_system_type():
    """获取当前系统类型"""
    if platform.system().lower() == 'windows':
        return 'windows'
    elif platform.system().lower() == 'linux':
        return 'linux'
    elif platform.system().lower() == 'darwin':
        return 'darwin'
    else:
        return 'unknown'

def find_available_chinese_fonts():
    """查找系统中可用的中文字体"""
    system = get_system_type()
    available_fonts = []
    
    # 检查字体名称
    for font_name in FONT_NAMES.get(system, []):
        if any(font_name.lower() in f.lower() for f in plt.rcParams['font.sans-serif']):
            available_fonts.append(font_name)
    
    # 检查字体文件
    for font_file in FONT_FILES.get(system, {}).values():
        if os.path.exists(font_file):
            available_fonts.append(font_file)
    
    return available_fonts

def print_font_info(verbose=False):
    """打印系统字体信息
    
    参数:
        verbose (bool): 是否显示详细信息
    """
    system = get_system_type()
    available_fonts = find_available_chinese_fonts()
    
    print(f"\n系统类型: {platform.system()} ({system})")
    print(f"Python版本: {platform.python_version()}")
    print(f"Matplotlib版本: {mpl.__version__}")
    
    print("\n可用中文字体:")
    if available_fonts:
        for i, font in enumerate(available_fonts, 1):
            print(f"  {i}. {font}")
    else:
        print("  未找到可用的中文字体")
    
    if verbose:
        print("\n字体配置信息:")
        print(f"  font.family: {plt.rcParams['font.family']}")
        print(f"  font.sans-serif (前5项): {plt.rcParams['font.sans-serif'][:5]}")
        print(f"  axes.unicode_minus: {plt.rcParams['axes.unicode_minus']}")
        
        print("\n系统预设字体:")
        for system_type, fonts in FONT_NAMES.items():
            if system_type == system:
                print(f"  当前系统 ({system_type}): {', '.join(fonts)}")
            elif verbose:
                print(f"  {system_type}: {', '.join(fonts)}")

def get_font_prop(font_size=12):
    """
    获取默认中文字体属性对象
    
    参数:
        font_size (int): 字体大小
        
    返回:
        matplotlib.font_manager.FontProperties: 字体属性对象
    """
    try:
        # 尝试常见中文字体，按优先级排序
        font_names = ['SimHei', 'Microsoft YaHei', 'SimSun', 'WenQuanYi Micro Hei', 
                     'Noto Sans CJK SC', 'PingFang SC', 'Heiti SC']
        
        # 检查每个字体是否可用
        for font_name in font_names:
            if font_name in plt.rcParams['font.sans-serif']:
                return FontProperties(family=font_name, size=font_size)
        
        # 如果没有找到合适的字体，使用默认字体
        return FontProperties(size=font_size)
    
    except Exception as e:
        logger.error(f"获取字体属性对象时出错: {str(e)}")
        return FontProperties(size=font_size)

def configure_matplotlib_fonts():
    """配置Matplotlib字体以支持中文显示"""
    try:
        # 检测系统
        system = platform.system()
        logger.info(f"操作系统: {system}")
        
        # 获取可用字体
        system_fonts = fm.findSystemFonts()
        chinese_fonts = []
        
        # 根据不同系统查找字体
        if system == 'Windows':
            # Windows系统默认中文字体
            target_fonts = ['SimHei', 'Microsoft YaHei', 'SimSun', 'FangSong']
        elif system == 'Darwin':
            # macOS系统默认中文字体
            target_fonts = ['PingFang SC', 'STHeiti', 'Heiti SC', 'Apple LiGothic']
        else:
            # Linux系统默认中文字体
            target_fonts = ['WenQuanYi Zen Hei', 'WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'Noto Sans SC']
        
        # 检查目标字体是否存在
        available_fonts = []
        for font in system_fonts:
            try:
                font_name = fm.FontProperties(fname=font).get_name()
                if any(target in font_name for target in target_fonts):
                    chinese_fonts.append(font)
                    available_fonts.append(font_name)
            except Exception:
                pass
        
        if available_fonts:
            logger.info(f"找到中文字体: {', '.join(available_fonts[:5])}" + 
                      (f" 等{len(available_fonts)}个" if len(available_fonts) > 5 else ""))
            
            # 设置全局字体
            plt.rcParams['font.family'] = ['sans-serif']
            plt.rcParams['font.sans-serif'] = available_fonts + ['DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号
            
            logger.info("成功配置matplotlib中文字体支持")
            return True
        else:
            logger.warning("没有找到合适的中文字体，将使用默认字体")
            plt.rcParams['font.family'] = ['sans-serif']
            plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
            return False
    
    except Exception as e:
        warnings.warn(f"设置中文字体支持时出错: {str(e)}")
        logger.error(f"设置中文字体支持时出错: {str(e)}")
        return False

def rebuild_font_cache():
    """
    重建matplotlib字体缓存
    解决中文字体无法显示的问题
    """
    try:
        import matplotlib.font_manager as fm
        print("正在重建字体缓存...")
        fm._rebuild()
        print("字体缓存重建完成，请重启应用程序以应用更改")
        return True
    except Exception as e:
        logger.error(f"重建字体缓存失败: {str(e)}")
        print(f"重建字体缓存失败: {str(e)}")
        return False

def test_font_display(output_file='font_test.png'):
    """测试字体显示"""
    font_prop = get_font_prop(14)
    
    # 创建图表
    plt.figure(figsize=(10, 6))
    
    # 创建示例数据
    x = np.linspace(0, 10, 100)
    y1 = np.sin(x)
    y2 = np.cos(x)
    
    # 绘制数据
    plt.plot(x, y1, 'r-', label='正弦曲线')
    plt.plot(x, y2, 'b--', label='余弦曲线')
    
    # 设置标题和标签
    plt.title('中文字体测试', fontproperties=font_prop, fontsize=16)
    plt.xlabel('X轴', fontproperties=font_prop, fontsize=12)
    plt.ylabel('Y轴', fontproperties=font_prop, fontsize=12)
    
    # 设置图例
    plt.legend(prop=font_prop)
    
    # 保存图表
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"测试图像已保存到: {output_file}")
    return output_file

def fix_legend_font(fig, font_size=10):
    """修复图例中的中文字体"""
    try:
        # 获取图例
        legend = fig.get_axes()[0].get_legend()
        if legend is not None:
            # 设置字体属性
            font_prop = get_font_prop(font_size)
            for text in legend.get_texts():
                text.set_fontproperties(font_prop)
            
            # 设置标题字体属性
            if legend.get_title():
                legend.get_title().set_fontproperties(font_prop)
        
        return True
    except Exception as e:
        logger.error(f"修复图例字体失败: {str(e)}")
        return False

# 当作为独立脚本运行时的测试功能
if __name__ == "__main__":
    configure_matplotlib_fonts()
    print_font_info(verbose=True)
    test_font_display() 