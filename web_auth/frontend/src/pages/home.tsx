import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ShieldCheck,
  Fingerprint,
  Radio,
  Zap,
  HeartPulse,
  Activity,
  ArrowRight,
  Cpu,
  Lock,
  Waves,
  type LucideIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  StaggerGroup,
  StaggerItem,
  Reveal,
  FadeUp,
  Magnetic,
  CountUp,
} from '@/components/motion'
import { EcgWave } from '@/components/visuals/ecg-wave'

/* ---------------- 内容数据 ---------------- */

interface Feature {
  icon: LucideIcon
  title: string
  desc: string
  metric: string
  metricLabel: string
}

const FEATURES: Feature[] = [
  {
    icon: ShieldCheck,
    title: '生物特征不可伪造',
    desc: '以心电与脉搏波形作为身份凭证，活体信号难以复制或盗用。',
    metric: '99.9',
    metricLabel: '认证准确率 %',
  },
  {
    icon: Zap,
    title: '秒级无感认证',
    desc: '连接设备后自动完成采集与比对，无需记忆或输入任何密码。',
    metric: '3',
    metricLabel: '秒内完成认证',
  },
  {
    icon: Fingerprint,
    title: '个体唯一性',
    desc: '每个人的心电波形如同指纹般独一无二，天然具备唯一标识能力。',
    metric: '1000',
    metricLabel: '特征点采样长度',
  },
]

interface Step {
  no: string
  icon: LucideIcon
  title: string
  desc: string
}

const STEPS: Step[] = [
  {
    no: '01',
    icon: Radio,
    title: '连接采集设备',
    desc: '通过蓝牙或串口接入心电手环，系统自动识别可用设备。',
  },
  {
    no: '02',
    icon: HeartPulse,
    title: '采集生理信号',
    desc: '安静状态下采集多段 ECG / PPG 波形，构建个体特征基线。',
  },
  {
    no: '03',
    icon: Cpu,
    title: '训练专属模型',
    desc: 'BiLSTM + Attention 网络学习你的波形特征，生成独立模型。',
  },
  {
    no: '04',
    icon: Lock,
    title: '完成身份认证',
    desc: '再次采集时比对特征相似度，达到阈值即确认身份。',
  },
]

/* ---------------- 页面 ---------------- */

export default function HomePage() {
  return (
    <div className="mx-auto max-w-7xl px-4 sm:px-6">
      {/* ============ Hero ============ */}
      <section className="relative flex min-h-[86vh] flex-col justify-center py-20">
        <StaggerGroup className="max-w-3xl" stagger={0.1}>
          <StaggerItem>
            <Badge variant="accent" className="mb-6 px-3 py-1">
              <span className="relative flex size-1.5">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-[hsl(var(--accent))] opacity-75" />
                <span className="relative inline-flex size-1.5 rounded-full bg-[hsl(var(--accent))]" />
              </span>
              基于 ECG / PPG 的无密码认证
            </Badge>
          </StaggerItem>

          <StaggerItem>
            <h1 className="text-4xl font-semibold leading-[1.12] tracking-tight sm:text-5xl lg:text-6xl">
              <span className="mb-3 block font-mono text-sm font-medium uppercase tracking-[0.22em] text-[hsl(var(--primary))] sm:text-base">
                CardioCrypt
              </span>
              让你的心跳
              <br />
              成为唯一的<span className="text-sheen">身份凭证</span>
            </h1>
          </StaggerItem>

          <StaggerItem>
            <p className="mt-6 max-w-xl text-base leading-relaxed text-[hsl(var(--muted-foreground))] sm:text-lg">
              采集心电与脉搏波形，通过深度模型提取个体化特征。
              无需密码、无需记忆，佩戴设备即可完成身份确认。
            </p>
          </StaggerItem>

          <StaggerItem>
            <div className="mt-9 flex flex-wrap items-center gap-3">
              <Magnetic>
                <Button variant="brand" size="lg" asChild>
                  <Link to="/login">
                    <Activity className="size-5" />
                    开始身份认证
                  </Link>
                </Button>
              </Magnetic>
              <Button variant="secondary" size="lg" asChild>
                <Link to="/register">
                  注册新用户
                  <ArrowRight className="size-4" />
                </Link>
              </Button>
            </div>
          </StaggerItem>
        </StaggerGroup>

        {/* 心电波形可视化 */}
        <FadeUp delay={0.5} className="mt-16 lg:mt-20">
          <div className="glass hairline-top relative overflow-hidden rounded-[var(--radius-2xl)] p-1">
            <div className="relative rounded-[calc(var(--radius-2xl)-4px)] bg-[hsl(var(--surface-1)/0.6)] px-4 py-6 sm:px-8">
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-medium text-[hsl(var(--muted-foreground))]">
                  <Waves className="size-3.5 text-[hsl(var(--primary))]" />
                  实时信号模拟
                </div>
                <div className="flex items-center gap-4">
                  <Stat label="心率" value={<CountUp value={72} suffix=" BPM" />} />
                  <Stat label="信号质量" value="优" />
                  <Stat label="采样率" value="100 Hz" />
                </div>
              </div>
              <EcgWave className="h-32 w-full sm:h-40" />
            </div>
          </div>
        </FadeUp>
      </section>

      {/* ============ 特性 · Bento Grid ============ */}
      <section className="py-20">
        <Reveal className="mb-12">
          <SectionHeading
            eyebrow="核心能力"
            title="为什么用生理信号做认证"
            desc="两个难以同时满足的诉求：足够难伪造，又足够易使用。"
          />
        </Reveal>

        <StaggerGroup className="grid gap-5 md:grid-cols-3" stagger={0.09}>
          {FEATURES.map((f) => (
            <StaggerItem key={f.title} className="h-full">
              <Card className="group h-full">
                <CardContent className="flex h-full flex-col p-6 pt-6">
                  <span className="mb-5 flex size-11 items-center justify-center rounded-[var(--radius-md)] bg-[hsl(var(--primary)/0.12)] ring-1 ring-[hsl(var(--primary)/0.26)] transition-transform duration-300 group-hover:scale-110">
                    <f.icon className="size-5 text-[hsl(var(--primary))]" />
                  </span>

                  <h3 className="text-base font-semibold tracking-tight">
                    {f.title}
                  </h3>
                  <p className="mt-2 flex-1 text-sm leading-relaxed text-[hsl(var(--muted-foreground))]">
                    {f.desc}
                  </p>

                  <div className="mt-6 border-t border-[hsl(var(--border)/0.6)] pt-4">
                    <div className="text-2xl font-semibold tracking-tight text-[hsl(var(--primary))]">
                      <CountUp value={Number(f.metric)} />
                    </div>
                    <div className="mt-0.5 text-xs text-[hsl(var(--muted-foreground))]">
                      {f.metricLabel}
                    </div>
                  </div>
                </CardContent>
              </Card>
            </StaggerItem>
          ))}
        </StaggerGroup>
      </section>

      {/* ============ 工作原理 ============ */}
      <section className="py-20">
        <Reveal className="mb-12">
          <SectionHeading
            eyebrow="工作原理"
            title="四步完成一次认证"
            desc="从设备接入到身份确认，整个流程对用户完全透明。"
          />
        </Reveal>

        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <Reveal key={s.no} delay={i * 0.09}>
              <Card className="group h-full">
                <CardContent className="p-6 pt-6">
                  <div className="mb-5 flex items-center justify-between">
                    <span className="flex size-10 items-center justify-center rounded-[var(--radius-md)] bg-[hsl(var(--secondary)/0.9)] text-[hsl(var(--muted-foreground))] transition-colors duration-300 group-hover:bg-[hsl(var(--accent)/0.14)] group-hover:text-[hsl(var(--accent))]">
                      <s.icon className="size-4.5" />
                    </span>
                    <span className="font-mono text-xs tracking-widest text-[hsl(var(--muted-foreground)/0.55)]">
                      {s.no}
                    </span>
                  </div>
                  <h3 className="text-sm font-semibold tracking-tight">
                    {s.title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-[hsl(var(--muted-foreground))]">
                    {s.desc}
                  </p>
                </CardContent>
              </Card>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ============ 技术架构 ============ */}
      <section className="py-20">
        <div className="grid items-center gap-10 lg:grid-cols-2">
          <Reveal>
            <SectionHeading
              eyebrow="技术实现"
              title="双模态信号融合"
              desc="心电与脉搏两路信号分别建模，按加权系数融合决策，兼顾稳定性与抗伪装能力。"
              align="left"
            />
            <div className="mt-8 space-y-3">
              {[
                { k: '网络结构', v: 'BiLSTM + Attention' },
                { k: '融合策略', v: 'α·ECG + β·PPG 加权' },
                { k: '相似度算法', v: 'DTW + 余弦相似度' },
                { k: '模型存储', v: '每用户独立模型 + LRU 缓存' },
              ].map((row) => (
                <div
                  key={row.k}
                  className="flex items-center justify-between rounded-[var(--radius-md)] border border-[hsl(var(--border)/0.6)] bg-[hsl(var(--secondary)/0.35)] px-4 py-3 transition-colors duration-250 hover:border-[hsl(var(--primary)/0.4)]"
                >
                  <span className="text-sm text-[hsl(var(--muted-foreground))]">
                    {row.k}
                  </span>
                  <span className="text-sm font-medium">{row.v}</span>
                </div>
              ))}
            </div>
          </Reveal>

          <Reveal delay={0.15}>
            <Card className="p-1">
              <div className="rounded-[calc(var(--radius-xl)-4px)] bg-[hsl(var(--surface-1)/0.5)] p-6">
                <div className="mb-5 flex items-center gap-2 text-xs font-medium text-[hsl(var(--muted-foreground))]">
                  <Cpu className="size-3.5 text-[hsl(var(--accent))]" />
                  认证决策链路
                </div>
                <ArchitectureFlow />
              </div>
            </Card>
          </Reveal>
        </div>
      </section>

      {/* ============ CTA ============ */}
      <section className="py-20">
        <Reveal>
          <Card className="overflow-hidden">
            <CardContent className="relative p-10 pt-10 text-center sm:p-14 sm:pt-14">
              <div
                aria-hidden
                className="pointer-events-none absolute inset-0 opacity-70"
                style={{
                  background:
                    'radial-gradient(ellipse 70% 90% at 50% 0%, hsl(var(--primary)/0.12), transparent 65%)',
                }}
              />
              <div className="relative">
                <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                  准备好用心跳登录了吗
                </h2>
                <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-[hsl(var(--muted-foreground))]">
                  注册后采集三组心电数据即可生成你的专属认证模型。
                </p>
                <div className="mt-8 flex flex-wrap justify-center gap-3">
                  <Magnetic>
                    <Button variant="brand" size="lg" asChild>
                      <Link to="/register">
                        <Fingerprint className="size-5" />
                        创建账号
                      </Link>
                    </Button>
                  </Magnetic>
                  <Button variant="secondary" size="lg" asChild>
                    <Link to="/manage/login">
                      <ShieldCheck className="size-4" />
                      管理入口
                    </Link>
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </Reveal>
      </section>
    </div>
  )
}

/* ---------------- 局部组件 ---------------- */

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="text-right">
      <div className="text-xs text-[hsl(var(--muted-foreground))]">{label}</div>
      <div className="text-sm font-medium text-[hsl(var(--foreground))]">
        {value}
      </div>
    </div>
  )
}

function SectionHeading({
  eyebrow,
  title,
  desc,
  align = 'center',
}: {
  eyebrow: string
  title: string
  desc: string
  align?: 'center' | 'left'
}) {
  return (
    <div className={align === 'center' ? 'mx-auto max-w-2xl text-center' : ''}>
      <div className="mb-3 text-xs font-medium uppercase tracking-[0.14em] text-[hsl(var(--accent))]">
        {eyebrow}
      </div>
      <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
        {title}
      </h2>
      <p className="mt-3 text-sm leading-relaxed text-[hsl(var(--muted-foreground))]">
        {desc}
      </p>
    </div>
  )
}

/** 认证决策链路图（纯 SVG + 动效） */
function ArchitectureFlow() {
  const nodes = [
    { label: '信号采集', sub: 'ECG / PPG' },
    { label: '特征提取', sub: '归一化 · 去噪' },
    { label: '模型推理', sub: 'BiLSTM' },
    { label: '相似度比对', sub: 'DTW · Cosine' },
    { label: '身份确认', sub: '阈值判定' },
  ]

  return (
    <div className="space-y-2.5">
      {nodes.map((n, i) => (
        <div key={n.label} className="relative">
          <motion.div
            initial={{ opacity: 0, x: -14 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: '-40px' }}
            transition={{
              duration: 0.5,
              delay: i * 0.09,
              ease: [0.22, 1, 0.36, 1],
            }}
            className="flex items-center gap-3.5 rounded-[var(--radius-md)] border border-[hsl(var(--border)/0.6)] bg-[hsl(var(--secondary)/0.45)] px-4 py-3 transition-colors duration-250 hover:border-[hsl(var(--accent)/0.45)]"
          >
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--primary)/0.14)] font-mono text-[0.65rem] font-medium text-[hsl(var(--primary))]">
              {i + 1}
            </span>
            <div className="flex-1">
              <div className="text-sm font-medium">{n.label}</div>
              <div className="text-xs text-[hsl(var(--muted-foreground))]">
                {n.sub}
              </div>
            </div>
            {i === nodes.length - 1 && (
              <span className="flex size-6 items-center justify-center rounded-full bg-[hsl(var(--accent)/0.16)]">
                <ShieldCheck className="size-3.5 text-[hsl(var(--accent))]" />
              </span>
            )}
          </motion.div>
          {i < nodes.length - 1 && (
            <div className="ml-[1.7rem] h-2.5 w-px bg-gradient-to-b from-[hsl(var(--border))] to-transparent" />
          )}
        </div>
      ))}
    </div>
  )
}
