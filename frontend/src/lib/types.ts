export type Offer = {
  retailer: string; seller: string | null; confidence: 'exact';
  product_name: string; brand: string | null; model: string | null; colourway: string | null;
  image_url: string | null; style_code: string | null; requested_uk_size: string; size_available: boolean;
  stock_status: 'in_stock' | 'out_of_stock' | 'unknown';
  category: 'footwear' | 'non_footwear' | 'unknown';
  department: 'men' | 'women' | 'kids' | 'unisex' | 'unknown';
  listed_price_paise: number; automatic_discount_paise: number; shipping_paise: number | null;
  effective_price_paise: number; conditional_offers: { kind: string; description: string; amount_paise: number | null }[];
  product_url: string; return_policy: string | null; match_score: number; last_checked: string;
};
export type RetailerStatus = {
  retailer_id: string | null; retailer: string; state: 'pending' | 'running' | 'complete' | 'partial' | 'error' | 'blocked' | 'timeout' | 'cached' | 'needs_session';
  offer_count: number; error: string | null; elapsed_ms: number | null;
  reason_code: string | null; http_status: number | null; retry_count: number; 
  circuit_state: 'closed' | 'open' | 'half_open';
  source: string | null; retry_at: string | null;
  session_capable: boolean; session_state: 'none' | 'starting' | 'active' | 'expired';
};
export type SearchResult = {
  id: string; state: 'running' | 'complete'; offers: Offer[];
  retailers: RetailerStatus[]; cached: boolean; created_at: string; completed_at: string | null;
  request: { query: string; uk_size: string; brand: string | null; colourway: string | null; department: string; pin_code: string | null };
};
