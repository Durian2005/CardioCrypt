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