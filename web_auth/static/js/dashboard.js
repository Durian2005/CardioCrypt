// 实时数据更新
let realtimeChart, heartrateChart, emotionChart;

function initCharts() {
    // Chart.js 全局配置 - 大屏风格
    Chart.defaults.color = '#00ffff';
    Chart.defaults.borderColor = 'rgba(0, 255, 255, 0.2)';
    // 初始化实时波形图
    const realtimeCtx = document.getElementById('realtime-chart').getContext('2d');
    realtimeChart = new Chart(realtimeCtx, {
        type: 'line',
        data: {
            labels: Array.from({length: 100}, (_, i) => i),
            datasets: [
                {
                    label: 'ECG信号',
                    borderColor: '#ff0080',
                        backgroundColor: 'rgba(255, 0, 128, 0.1)',
                        data: Array(100).fill(0),
                        borderWidth: 2,
                        tension: 0.4,
                        pointRadius: 0,
                        pointHoverRadius: 5,
                        shadowColor: '#ff0080',
                        shadowBlur: 10
                },
                {
                    label: 'PPG信号',
                    borderColor: '#00ffff',
                    backgroundColor: 'rgba(0, 255, 255, 0.1)',
                    data: Array(100).fill(0),
                    borderWidth: 2,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 5
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
        plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        labels: {
                            color: '#00ffff',
                            font: {
                                size: 12,
                                weight: '600'
                            },
                            usePointStyle: true,
                            padding: 15
                        }
                    },
        tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        titleColor: '#00ffff',
                        bodyColor: '#fff',
                        borderColor: '#00ffff',
                        borderWidth: 1,
                        padding: 10,
                        displayColors: true
                    }
                },
        scales: {
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: 'rgba(0, 255, 255, 0.1)',
                            drawBorder: false
                        },
                        ticks: {
                            color: '#00ffff',
                            font: {
                                size: 11
                            }
                        }
                    },
        x: {
                        grid: {
                            color: 'rgba(0, 255, 255, 0.05)',
                            drawBorder: false
                        },
                        ticks: {
                            color: '#00ffff',
                            font: {
                                size: 11
                            },
                            maxTicksLimit: 10
                        }
                    }
                }
            }
        });

    // 其他图表初始化...
}

// 更新实时数据
let lastAlertLevel = ''; // 记录上一次的预警等级，避免重复弹窗
function updateRealtimeData() {
    fetch('/api/realtime_health_data')
        .then(response => response.json())
        .then(data => {
            // 更新界面数据
            document.getElementById('current-heartrate').textContent = data.heartrate;
            document.getElementById('emotion-status').textContent = data.emotion;
            document.getElementById('alert-level').textContent = data.alertLevel;
            document.getElementById('last-update').textContent = '更新于: ' + new Date().toLocaleTimeString();
            // 检查预警等级，如果是高风险则弹出警告
            checkAlertLevel(data.alert_level);
            // 更新实时图表数据
                updateChartData(realtimeChart, data.ecg_signal, data.ppg_signal);
        });

}

// 检查预警等级并触发弹窗
    function checkAlertLevel(alertLevel) {
        // 更新预警卡片的样式
        updateAlertCardStyle(alertLevel);

        // 检测是否为高风险，并且与上次状态不同（避免重复弹窗）
        if ((alertLevel === '高风险' || alertLevel === '高') && lastAlertLevel !== '高风险') {
            showHighRiskAlert();
            lastAlertLevel = '高风险';

            // 播放警告音（如果浏览器支持）
            try {
                const audio = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2/LDciUFLIHO8tiJNwgZaLvt559NEAxQp+PwtmMcBjiR1/LMeSwFJHfH8N2QQAoUXrTp66hVFApGn+DyvmwhBzKJ0fPTgjMGHm7A7+OZRQ0PVKvo7qxbGAg+ldjwzXgpBSF1x+/hlEILD1iy6OyrWhgIPpTY8Mx3KAUhdsfw4ZRCCw9YsujsrFoYCD6U2PDMdygFIXbH8OGUQ==');
                audio.play().catch(e => console.log('无法播放警告音'));
            } catch(e) {
                console.log('浏览器不支持音频播放');
            }
        } else if (alertLevel !== '高风险' && alertLevel !== '高') {
            lastAlertLevel = alertLevel;
        }
    }
  // 更新预警卡片样式
    function updateAlertCardStyle(alertLevel) {
        const alertLevelElement = document.getElementById('alert-level');
        const alertCard = alertLevelElement.closest('.card');
        const badgeElement = alertCard.querySelector('.badge');
        const iconElement = alertCard.querySelector('.fa-exclamation-triangle');

        // 移除所有可能的旧样式
        badgeElement.className = 'badge';
        iconElement.className = 'fas fa-exclamation-triangle fa-2x mb-3';
         // 根据预警等级设置不同的样式
        if (alertLevel === '高风险' || alertLevel === '高') {
            badgeElement.classList.add('bg-danger');
            badgeElement.textContent = '高风险';
            iconElement.classList.add('text-danger');
            alertCard.style.borderLeft = '5px solid #dc3545';
            alertCard.style.animation = 'shake 0.5s ease-in-out';
        } else if (alertLevel === '中风险' || alertLevel === '中') {
            badgeElement.classList.add('bg-warning');
            badgeElement.textContent = '中风险';
            iconElement.classList.add('text-warning');
            alertCard.style.borderLeft = '5px solid #ffc107';
            alertCard.style.animation = 'none';
        } else {
            badgeElement.classList.add('bg-success');
            badgeElement.textContent = '低风险';
            iconElement.classList.add('text-warning');
            alertCard.style.borderLeft = 'none';
            alertCard.style.animation = 'none';
        }
    }
    // 显示高风险预警弹窗
    function showHighRiskAlert() {
        const modal = new bootstrap.Modal(document.getElementById('highRiskAlertModal'));
        document.getElementById('alertTime').textContent = '预警时间: ' + new Date().toLocaleString();
        modal.show();
    // 可选：发送通知（需要用户授权）
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('健康监护预警', {
                body: '检测到高风险状态，请立即查看！',
                icon: '/static/images/warning-icon.png',
                badge: '/static/images/badge-icon.png',
                requireInteraction: true
            });
        }
    }

    // 更新图表数据
    function updateChartData(chart, ecgData, ppgData) {
        if (ecgData && chart.data.datasets[0]) {
            chart.data.datasets[0].data = ecgData;
        }
        if (ppgData && chart.data.datasets[1]) {
            chart.data.datasets[1].data = ppgData;
        }
        chart.update('none');
    }

    // 请求通知权限
    function requestNotificationPermission() {
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission().then(permission => {
                if (permission === 'granted') {
                    console.log('通知权限已授予');
                }
            });
        }
    }

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    initCharts();
    updateRealtimeData();
    requestNotificationPermission(); // 请求通知权限
    setInterval(updateRealtimeData, 3000); // 每3秒更新一次数据
});