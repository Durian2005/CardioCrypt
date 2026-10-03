#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Matplotlib设置模块
配置matplotlib绘图环境
"""

from .font_utils import configure_matplotlib_fonts
import matplotlib.pyplot as plt

def configure_matplotlib():
    """配置matplotlib环境"""
    # 设置中文字体支持
    configure_matplotlib_fonts()
    
    # 设置绘图样式
    plt.style.use('ggplot')
    
    # 设置图表尺寸
    plt.rcParams['figure.figsize'] = (10, 6)
    plt.rcParams['figure.dpi'] = 100
    
    # 设置线条宽度
    plt.rcParams['lines.linewidth'] = 2
    
    # 设置标题和标签大小
    plt.rcParams['axes.titlesize'] = 16
    plt.rcParams['axes.labelsize'] = 12
    
    # 设置图例样式
    plt.rcParams['legend.fontsize'] = 10
    plt.rcParams['legend.frameon'] = True
    plt.rcParams['legend.facecolor'] = 'white'
    plt.rcParams['legend.edgecolor'] = 'gray'
    plt.rcParams['legend.framealpha'] = 0.8
    
    # 设置网格线
    plt.rcParams['grid.linestyle'] = '--'
    plt.rcParams['grid.alpha'] = 0.7
    
    # 设置保存图片时的背景透明度
    plt.rcParams['savefig.transparent'] = False
    
    # 设置交互模式（根据需要调整）
    plt.ion()  # 打开交互模式
    
    return True 