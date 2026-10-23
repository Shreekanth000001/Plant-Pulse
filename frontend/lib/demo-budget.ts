export interface DemoBudgetState {
  isExhausted: boolean;
  remainingSeconds: number | null;
  resetsAt?: string;
}

export interface DemoBudgetBannerProps {
  visible: boolean;
  text: string;
  videoUrl?: string;
}

export function getDemoBudgetBannerProps(
  state: DemoBudgetState,
  videoUrl?: string
): DemoBudgetBannerProps | null {
  if (!state.isExhausted) {
    return null;
  }
  return {
    visible: true,
    text: "Daily demo limit reached, resets at 00:00 UTC",
    videoUrl: videoUrl && videoUrl.trim() !== "" ? videoUrl : undefined,
  };
}

