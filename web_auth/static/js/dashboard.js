// 仪表盘JavaScript功能
class DashboardManager {
    constructor() {
        this.ecgChart = null;
        this.init();
    }

    init() {
        this.initECGChart();
        this.initGauges();
        this.initTimeline();
        this.startRealTimeUpdates();
        this.initSystemMetrics();
    }

    // 初始化ECG实时波形图
    initECGChart() {
        const ctx = document.getElementById('ecgChart');
        if (!ctx) return;

        // 生成模拟ECG数据
        const generateECGData = () => {
            const data = [];
            const timePoints = 100;
            for (let i = 0; i < timePoints; i++) {
                const t = i / timePoints * 4 * Math.PI;
                // 模拟ECG波形：P波、QRS复合波、T波
                let value = 0;
                
                // P波
                if (t >= 0 && t < 0.5) {
                    value = 0.3 * Math.sin(t * 4);
                }
                // QRS复合波
                else if (t >= 0.5 && t < 1.5) {
                    value = 2.0 * Math.sin((t - 0.5) * 8) - 0.5 * Math.sin((t - 0.5) * 16);
                }
                // T波
                else if (t >= 1.5 && t < 2.5) {
                    value = 0.8 * Math.sin((t - 1.5) * 2);
                }
                // 基线
                else {
                    value = 0.1 * Math.sin(t * 0.5);
                }
                
                data.push({
                    x: i,
                    y: value + Math.random() * 0.1
                });
            }
            return data;
        };

        this.ecgChart = new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [{
                    label: 'ECG信号',
                    data: generateECGData(),
                    borderColor: '#00ff00',
                    backgroundColor: 'rgba(0, 255, 0, 0.1)',
                    borderWidth: 2,
                    fill: false,
                    tension: 0.1,
                    pointRadius: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: {
                    duration: 0
                },
                scales: {
                    x: {
                        display: false,
                        grid: {
                            display: false
                        }
                    },
                    y: {
                        display: false,
                        grid: {
                            display: false
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    }
                },
                elements: {
                    point: {
                        radius: 0
                    }
                }
            }
        });

        // 实时更新ECG数据
        setInterval(() => {
            if (this.ecgChart) {
                const newData = generateECGData();
                this.ecgChart.data.datasets[0].data = newData;
                this.ecgChart.update('none');
            }
        }, 1000);
    }





    // 初始化仪表盘
    initGauges() {
        this.updateGauge('successRate', 96.5);
        this.updateGauge('accuracyRate', 98.2);
        this.updateGauge('responseTime', 85);
    }

    // 更新仪表盘
    updateGauge(elementId, value) {
        const element = document.getElementById(elementId);
        if (!element) return;

        const percentage = (value / 100) * 360;
        const gauge = element.querySelector('.gauge');
        if (gauge) {
            gauge.style.background = `conic-gradient(from 0deg, #28a745 0deg, #28a745 ${percentage}deg, #e9ecef ${percentage}deg)`;
        }

        const valueElement = element.querySelector('.gauge-value');
        if (valueElement) {
            valueElement.textContent = value + (elementId === 'responseTime' ? 'ms' : '%');
        }
    }

    // 初始化时间线
    initTimeline() {
        const timeline = document.getElementById('securityTimeline');
        if (!timeline) return;

        // 基于当前时间生成事件（2分半内）
        const now = new Date();
        const events = [
            { 
                time: new Date(now.getTime() - 15 * 1000).toLocaleTimeString('zh-CN', {hour12: false}), 
                event: '用户认证成功', 
                status: 'success' 
            },
            { 
                time: new Date(now.getTime() - 45 * 1000).toLocaleTimeString('zh-CN', {hour12: false}), 
                event: 'ECG信号采集完成', 
                status: 'success' 
            },
            { 
                time: new Date(now.getTime() - 75 * 1000).toLocaleTimeString('zh-CN', {hour12: false}), 
                event: '设备连接建立', 
                status: 'success' 
            },
            { 
                time: new Date(now.getTime() - 105 * 1000).toLocaleTimeString('zh-CN', {hour12: false}), 
                event: '系统自检完成', 
                status: 'success' 
            },
            { 
                time: new Date(now.getTime() - 135 * 1000).toLocaleTimeString('zh-CN', {hour12: false}), 
                event: '用户登录尝试', 
                status: 'warning' 
            },
            { 
                time: new Date(now.getTime() - 150 * 1000).toLocaleTimeString('zh-CN', {hour12: false}), 
                event: '系统启动完成', 
                status: 'success' 
            }
        ];

        timeline.innerHTML = events.map(event => `
            <div class="timeline-item ${event.status}">
                <div class="d-flex justify-content-between">
                    <strong>${event.event}</strong>
                    <small class="text-muted">${event.time}</small>
                </div>
            </div>
        `).join('');
    }

    // 初始化系统指标
    initSystemMetrics() {
        this.updateSystemMetrics();
        setInterval(() => this.updateSystemMetrics(), 3000);
    }

    // 更新系统指标
    updateSystemMetrics() {
        // 模拟系统指标数据
        const metrics = {
            cpu: Math.floor(Math.random() * 20) + 15,
            memory: Math.floor(Math.random() * 15) + 25,
            disk: Math.floor(Math.random() * 10) + 30,
            network: Math.floor(Math.random() * 5) + 2
        };

        // 更新进度条
        Object.keys(metrics).forEach(key => {
            const element = document.getElementById(`${key}Progress`);
            if (element) {
                element.style.width = metrics[key] + '%';
                element.textContent = metrics[key] + '%';
            }
        });

        // 更新设备状态
        this.updateDeviceStatus();
    }

    // 更新设备状态
    updateDeviceStatus() {
        const deviceStatus = document.getElementById('deviceStatus');
        if (deviceStatus) {
            const isConnected = Math.random() > 0.1; // 90%连接率
            deviceStatus.innerHTML = `
                <span class="status-indicator ${isConnected ? 'status-online' : 'status-offline'}"></span>
                ${isConnected ? '设备已连接' : '设备离线'}
            `;
        }

        // 更新信号强度
        const signalStrength = document.getElementById('signalStrength');
        if (signalStrength) {
            const strength = Math.floor(Math.random() * 20) + 80;
            signalStrength.textContent = strength + ' dBm';
        }
    }

    // 开始实时更新
    startRealTimeUpdates() {
        // 更新当前时间
        setInterval(() => {
            const timeElement = document.getElementById('currentTime');
            if (timeElement) {
                timeElement.textContent = new Date().toLocaleTimeString('zh-CN');
            }
        }, 1000);

        // 更新心率数据
        setInterval(() => {
            const heartRateElement = document.getElementById('heartRate');
            if (heartRateElement) {
                const heartRate = Math.floor(Math.random() * 20) + 65;
                heartRateElement.textContent = heartRate + ' BPM';
            }
        }, 2000);
    }
}

// 页面加载完成后初始化仪表盘
document.addEventListener('DOMContentLoaded', function() {
    // 加载Chart.js
    if (typeof Chart === 'undefined') {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/chart.js';
        script.onload = () => {
            new DashboardManager();
        };
        document.head.appendChild(script);
    } else {
        new DashboardManager();
    }

    // 添加页面动画效果
    const cards = document.querySelectorAll('.dashboard-card');
    cards.forEach((card, index) => {
        card.style.animationDelay = (index * 0.1) + 's';
        card.classList.add('fade-in');
    });
});

// 模拟数据生成函数
function generateMockData() {
    return {
        userStats: {
            totalLogins: 156,
            successfulAuths: 148,
            failedAuths: 8,
            avgResponseTime: 112
        },
        systemStats: {
            uptime: '7天 14小时 32分钟',
            activeUsers: 3,
            totalDevices: 2,
            dataIntegrity: 99.8
        },
        securityEvents: [
            { time: '14:32:15', type: '认证成功', user: 'user123', ip: '192.168.1.100' },
            { time: '14:30:42', type: '设备连接', user: 'user456', ip: '192.168.1.101' },
            { time: '14:29:18', type: '系统自检', user: 'system', ip: 'localhost' }
        ]
    };
} 