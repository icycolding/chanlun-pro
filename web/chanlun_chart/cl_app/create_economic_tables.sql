-- 创建经济指标数据表
CREATE TABLE IF NOT EXISTS economic_indicators (
    id SERIAL PRIMARY KEY,
    data_id VARCHAR(100) UNIQUE NOT NULL,
    country_code VARCHAR(10) NOT NULL DEFAULT 'US',
    indicator_name VARCHAR(200) NOT NULL,
    release_datetime TIMESTAMP WITH TIME ZONE NOT NULL,
    actual DECIMAL(20,6),
    forecast DECIMAL(20,6),
    previous DECIMAL(20,6),
    importance VARCHAR(20) DEFAULT 'medium',
    release_type VARCHAR(50) DEFAULT 'scheduled',
    unit VARCHAR(50) DEFAULT '',
    frequency VARCHAR(20) DEFAULT 'monthly',
    source VARCHAR(100) DEFAULT '',
    category VARCHAR(100) DEFAULT '',
    description TEXT DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 创建索引以提高查询性能
CREATE INDEX IF NOT EXISTS idx_economic_indicators_country_code ON economic_indicators(country_code);
CREATE INDEX IF NOT EXISTS idx_economic_indicators_indicator_name ON economic_indicators(indicator_name);
CREATE INDEX IF NOT EXISTS idx_economic_indicators_release_datetime ON economic_indicators(release_datetime);
CREATE INDEX IF NOT EXISTS idx_economic_indicators_importance ON economic_indicators(importance);
CREATE INDEX IF NOT EXISTS idx_economic_indicators_category ON economic_indicators(category);
CREATE INDEX IF NOT EXISTS idx_economic_indicators_created_at ON economic_indicators(created_at);

-- 创建复合索引
CREATE INDEX IF NOT EXISTS idx_economic_indicators_country_indicator ON economic_indicators(country_code, indicator_name);
CREATE INDEX IF NOT EXISTS idx_economic_indicators_indicator_release ON economic_indicators(indicator_name, release_datetime);

-- 创建触发器函数来自动更新 updated_at 字段
CREATE OR REPLACE FUNCTION update_economic_indicators_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 创建触发器
DROP TRIGGER IF EXISTS trigger_update_economic_indicators_updated_at ON economic_indicators;
CREATE TRIGGER trigger_update_economic_indicators_updated_at
    BEFORE UPDATE ON economic_indicators
    FOR EACH ROW
    EXECUTE FUNCTION update_economic_indicators_updated_at();

-- 添加表注释
COMMENT ON TABLE economic_indicators IS '经济指标数据表，存储各国经济指标的实际值、预测值和历史值';
COMMENT ON COLUMN economic_indicators.data_id IS '数据唯一标识符';
COMMENT ON COLUMN economic_indicators.country_code IS '国家代码，如US、CN、EU等';
COMMENT ON COLUMN economic_indicators.indicator_name IS '经济指标名称';
COMMENT ON COLUMN economic_indicators.release_datetime IS '数据发布时间';
COMMENT ON COLUMN economic_indicators.actual IS '实际值';
COMMENT ON COLUMN economic_indicators.forecast IS '预测值';
COMMENT ON COLUMN economic_indicators.previous IS '前值';
COMMENT ON COLUMN economic_indicators.importance IS '重要性级别：low, medium, high';
COMMENT ON COLUMN economic_indicators.release_type IS '发布类型：scheduled, revised, preliminary等';
COMMENT ON COLUMN economic_indicators.unit IS '数据单位';
COMMENT ON COLUMN economic_indicators.frequency IS '发布频率：daily, weekly, monthly, quarterly, yearly';
COMMENT ON COLUMN economic_indicators.source IS '数据来源';
COMMENT ON COLUMN economic_indicators.category IS '指标分类';
COMMENT ON COLUMN economic_indicators.description IS '指标描述';

-- 创建视图以便于查询最新数据
CREATE OR REPLACE VIEW latest_economic_indicators AS
SELECT DISTINCT ON (country_code, indicator_name) 
    id, data_id, country_code, indicator_name, release_datetime,
    actual, forecast, previous, importance, release_type,
    unit, frequency, source, category, description, created_at
FROM economic_indicators
ORDER BY country_code, indicator_name, release_datetime DESC;

COMMENT ON VIEW latest_economic_indicators IS '最新经济指标数据视图，每个国家的每个指标只显示最新的一条记录';

-- 创建函数来获取指标的历史趋势
CREATE OR REPLACE FUNCTION get_indicator_trend(
    p_country_code VARCHAR(10),
    p_indicator_name VARCHAR(200),
    p_limit INTEGER DEFAULT 12
)
RETURNS TABLE(
    release_datetime TIMESTAMP WITH TIME ZONE,
    actual DECIMAL(20,6),
    forecast DECIMAL(20,6),
    previous DECIMAL(20,6),
    trend_direction VARCHAR(10)
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ei.release_datetime,
        ei.actual,
        ei.forecast,
        ei.previous,
        CASE 
            WHEN LAG(ei.actual) OVER (ORDER BY ei.release_datetime) IS NULL THEN 'neutral'
            WHEN ei.actual > LAG(ei.actual) OVER (ORDER BY ei.release_datetime) THEN 'up'
            WHEN ei.actual < LAG(ei.actual) OVER (ORDER BY ei.release_datetime) THEN 'down'
            ELSE 'neutral'
        END as trend_direction
    FROM economic_indicators ei
    WHERE ei.country_code = p_country_code 
      AND ei.indicator_name = p_indicator_name
      AND ei.actual IS NOT NULL
    ORDER BY ei.release_datetime DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_indicator_trend IS '获取指定国家和指标的历史趋势数据';

-- 插入一些示例数据（可选）
-- INSERT INTO economic_indicators (data_id, country_code, indicator_name, release_datetime, actual, forecast, previous, importance, category, description)
-- VALUES 
--     ('US_GDP_2024Q1', 'US', 'GDP Growth Rate', '2024-01-26 14:30:00+00', 3.2, 3.1, 2.9, 'high', 'Growth', 'Quarterly GDP growth rate'),
--     ('US_CPI_202401', 'US', 'Consumer Price Index', '2024-01-11 14:30:00+00', 3.4, 3.2, 3.1, 'high', 'Inflation', 'Monthly consumer price index'),
--     ('US_NFP_202401', 'US', 'Non-Farm Payrolls', '2024-01-05 14:30:00+00', 216000, 200000, 199000, 'high', 'Employment', 'Monthly non-farm payroll employment change');

-- 显示创建结果
SELECT 'Economic indicators table and related objects created successfully!' as result;