import { Link } from 'react-router-dom'
import { Home, SearchX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { FadeUp } from '@/components/motion'
import { EcgWave } from '@/components/visuals/ecg-wave'

export default function NotFoundPage() {
  return (
    <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center px-4 py-12 sm:px-6">
      <FadeUp className="w-full max-w-lg">
        <Card>
          <CardContent className="p-8 pt-8 text-center">
            <div className="mx-auto mb-5 flex size-14 items-center justify-center rounded-full bg-[hsl(var(--secondary)/0.8)] ring-1 ring-[hsl(var(--border))]">
              <SearchX className="size-6 text-[hsl(var(--muted-foreground))]" />
            </div>
            <h1 className="text-4xl font-semibold tracking-tight">404</h1>
            <p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
              未找到该页面，也许信号传输途中丢失了
            </p>

            <div className="my-7 overflow-hidden rounded-[var(--radius-lg)] border border-[hsl(var(--border)/0.6)] bg-[hsl(var(--surface-1)/0.5)] p-3">
              <EcgWave className="h-16 w-full" strokeClass="text-[hsl(var(--muted-foreground))]" />
            </div>

            <Button variant="brand" asChild>
              <Link to="/">
                <Home className="size-4" />
                返回首页
              </Link>
            </Button>
          </CardContent>
        </Card>
      </FadeUp>
    </div>
  )
}
