-- ============================================================
-- 超商評論平台 MVP — Supabase (PostgreSQL) Schema
-- ============================================================
-- 使用者表不用自己刻，Supabase 內建 auth.users 就有登入/驗證，
-- 我們只需要一張 profiles 表補「暱稱」這種額外欄位，用 user id
-- 對應回 auth.users，這是 Supabase 官方推薦的標準寫法。

create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  nickname text not null,
  created_at timestamptz not null default now()
);

-- 商品目錄：只從活動/新品擷取結果自動長出來，不開放使用者手動新增
create table products (
  id bigint generated always as identity primary key,
  name text not null unique,          -- unique 避免程式邏輯漏接時仍重複寫入
  category text default '未分類',
  image_url text,
  source_url text,
  scraped_at timestamptz not null default now()
);

-- 活動促銷：獨立表，不綁 product_id（MVP 階段刻意的設計決定）
create table activities (
  id bigint generated always as identity primary key,
  title text not null,
  description text,                   -- 含原價/特價文字說明
  start_date date,
  end_date date,
  source_url text,
  scraped_at timestamptz not null default now()
);

-- 食べたい（想吃）：低門檻互動，不需要吃過就能按，用來緩解冷啟動問題
create table wants (
  id bigint generated always as identity primary key,
  product_id bigint not null references products(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (product_id, user_id)        -- 同一人對同一商品只能按一次，可取消
);

-- 評分
create table ratings (
  id bigint generated always as identity primary key,
  product_id bigint not null references products(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  score smallint not null check (score between 1 and 5),
  created_at timestamptz not null default now(),
  unique (product_id, user_id)        -- 一個使用者對同一商品只能評一次分（可更新，不能洗分）
);

-- 留言
create table comments (
  id bigint generated always as identity primary key,
  product_id bigint not null references products(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  content text not null check (char_length(content) between 1 and 500),
  created_at timestamptz not null default now()
);

-- 常用查詢索引
create index idx_ratings_product on ratings(product_id);
create index idx_comments_product on comments(product_id);
create index idx_activities_dates on activities(start_date, end_date);

-- ============================================================
-- Row Level Security（Supabase 預設會鎖表，要手動開放權限）
-- ============================================================
alter table wants enable row level security;
alter table products enable row level security;
alter table activities enable row level security;
alter table ratings enable row level security;
alter table comments enable row level security;
alter table profiles enable row level security;

-- 商品/活動：任何人（含未登入）都能看
create policy "wants are viewable by everyone" on wants for select using (true);
create policy "users can insert their own want" on wants for insert with check (auth.uid() = user_id);
create policy "users can delete their own want" on wants for delete using (auth.uid() = user_id);

create policy "products are viewable by everyone" on products for select using (true);
create policy "activities are viewable by everyone" on activities for select using (true);

-- 評分/留言：任何人都能看，但只有登入且是本人才能新增/修改/刪除自己的資料
create policy "ratings are viewable by everyone" on ratings for select using (true);
create policy "users can insert their own rating" on ratings for insert with check (auth.uid() = user_id);
create policy "users can update their own rating" on ratings for update using (auth.uid() = user_id);
create policy "users can delete their own rating" on ratings for delete using (auth.uid() = user_id);

create policy "comments are viewable by everyone" on comments for select using (true);
create policy "users can insert their own comment" on comments for insert with check (auth.uid() = user_id);
create policy "users can delete their own comment" on comments for delete using (auth.uid() = user_id);

create policy "profiles are viewable by everyone" on profiles for select using (true);
create policy "users can update their own profile" on profiles for update using (auth.uid() = id);
