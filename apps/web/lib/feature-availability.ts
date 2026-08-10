/**
 * Website availability switches for implemented features that are intentionally
 * kept out of production. Keep the dormant-feature inventory in sync when a
 * switch changes.
 */
export const FEATURE_AVAILABILITY = {
  customSignal: false,
  alternativeSignal: false,
  robustSignal: false,
} as const;
