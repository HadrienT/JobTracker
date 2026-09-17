import { PrimitivesDemo } from '@/app/primitives-demo'
import { ThemeProvider } from '@/app/theme-provider'
import { TooltipProvider } from '@/shared/ui/tooltip'

export function App() {
  return (
    <ThemeProvider>
      <TooltipProvider delayDuration={150}>
        <PrimitivesDemo />
      </TooltipProvider>
    </ThemeProvider>
  )
}
