/**
 * 心电脉搏信号身份认证系统 - 主JavaScript文件
 */

// 页面加载完成后执行
$(document).ready(function() {
    // 初始化工具提示
    initTooltips();
    
    // 自动隐藏警告消息
    autoHideAlerts();
    
    // 监听表单提交
    handleFormSubmission();
    
    // 初始化数据采集步骤
    initDataCollectionSteps();
});

/**
 * 初始化Bootstrap工具提示
 */
function initTooltips() {
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

/**
 * 自动隐藏警告消息
 */
function autoHideAlerts() {
    // 5秒后自动隐藏警告消息
    setTimeout(function() {
        $('.alert-dismissible').alert('close');
    }, 5000);
}

/**
 * 处理表单提交
 */
function handleFormSubmission() {
    // 监听表单提交事件
    $('form').on('submit', function() {
        // 禁用提交按钮，防止重复提交
        $(this).find('button[type="submit"]').prop('disabled', true);
        $(this).find('button[type="submit"]').html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> 处理中...');
    });
}

/**
 * 显示加载动画
 * @param {string} selector - 目标元素选择器
 * @param {string} message - 显示消息
 */
function showLoading(selector, message) {
    $(selector).html(`
        <div class="text-center">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <p class="mt-2">${message || '加载中...'}</p>
        </div>
    `);
}

/**
 * 显示错误消息
 * @param {string} selector - 目标元素选择器
 * @param {string} message - 错误消息
 */
function showError(selector, message) {
    $(selector).html(`
        <div class="alert alert-danger" role="alert">
            <i class="fas fa-exclamation-circle me-2"></i>
            ${message || '发生错误，请重试'}
        </div>
    `);
}

/**
 * 显示成功消息
 * @param {string} selector - 目标元素选择器
 * @param {string} message - 成功消息
 */
function showSuccess(selector, message) {
    $(selector).html(`
        <div class="alert alert-success" role="alert">
            <i class="fas fa-check-circle me-2"></i>
            ${message || '操作成功'}
        </div>
    `);
}

/**
 * 格式化日期时间
 * @param {Date} date - 日期对象
 * @returns {string} - 格式化后的日期时间字符串
 */
function formatDateTime(date) {
    if (!date) return '';
    
    const options = {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    };
    
    return date.toLocaleString('zh-CN', options);
}

/**
 * 初始化数据采集步骤
 */
function initDataCollectionSteps() {
    const stepProgressBar = $('#step-progress-bar');
    const steps = $('.step');
    const stepContents = $('.step-content');
    
    if (stepProgressBar.length === 0) return;
    
    // 更新步骤进度
    function updateStepProgress(currentStep) {
        const progress = (currentStep / (steps.length - 1)) * 100;
        stepProgressBar.css('width', progress + '%');
        
        // 更新步骤状态
        steps.removeClass('active');
        for (let i = 0; i <= currentStep; i++) {
            $(steps[i]).addClass('active');
        }
        
        // 显示当前步骤内容
        stepContents.removeClass('active');
        $(`#step-${currentStep + 1}-content`).addClass('active');
    }
    
    // 初始化第一步
    updateStepProgress(0);
    
    // 绑定步骤切换事件
    window.switchToStep = function(stepNumber) {
        updateStepProgress(stepNumber);
    };
    
    // 添加步骤动画效果
    steps.on('click', function() {
        const stepIndex = $(this).index();
        updateStepProgress(stepIndex);
    });
}

/**
 * 设备扫描功能
 */
function scanDevices() {
    const devicesList = $('#devices-list');
    const devicesListGroup = $('#devices-list-group');
    
    // 显示扫描中状态
    devicesList.removeClass('d-none');
    devicesListGroup.html(`
        <div class="text-center py-3">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">扫描中...</span>
            </div>
            <p class="mt-2">正在扫描设备...</p>
        </div>
    `);
    
    // 模拟设备扫描
    setTimeout(function() {
        const mockDevices = [
            { name: 'ECG-Device-001', address: '00:11:22:33:44:55', rssi: -45 },
            { name: 'ECG-Device-002', address: '00:11:22:33:44:66', rssi: -52 },
            { name: 'PPG-Sensor-001', address: '00:11:22:33:44:77', rssi: -48 }
        ];
        
        let devicesHtml = '';
        mockDevices.forEach(device => {
            const signalStrength = device.rssi > -50 ? '强' : device.rssi > -60 ? '中' : '弱';
            const signalClass = device.rssi > -50 ? 'text-success' : device.rssi > -60 ? 'text-warning' : 'text-danger';
            
            devicesHtml += `
                <div class="list-group-item list-group-item-action" data-device="${device.address}">
                    <div class="d-flex w-100 justify-content-between align-items-center">
                        <div>
                            <h6 class="mb-1">${device.name}</h6>
                            <small class="text-muted">${device.address}</small>
                        </div>
                        <div class="text-end">
                            <span class="badge bg-primary">${signalStrength}</span>
                            <small class="text-muted d-block">${device.rssi} dBm</small>
                        </div>
                    </div>
                </div>
            `;
        });
        
        devicesListGroup.html(devicesHtml);
        
        // 绑定设备选择事件
        devicesListGroup.find('.list-group-item').on('click', function() {
            devicesListGroup.find('.list-group-item').removeClass('active');
            $(this).addClass('active');
        });
    }, 2000);
}

/**
 * 连接设备功能
 */
function connectDevice(deviceAddress) {
    return new Promise((resolve, reject) => {
        // 模拟连接过程
        setTimeout(() => {
            const success = Math.random() > 0.2; // 80%成功率
            if (success) {
                resolve();
            } else {
                reject(new Error('连接失败'));
            }
        }, 3000);
    });
}

/**
 * 数据采集功能
 */
function startDataCollection() {
    return new Promise((resolve) => {
        // 模拟数据采集过程
        setTimeout(() => {
            resolve();
        }, 5000);
    });
} 