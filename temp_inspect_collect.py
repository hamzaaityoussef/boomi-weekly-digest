from src.collect import collect_scrape
import yaml

with open('config.yaml', 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

for page_cfg in cfg['scrape_pages']:
    items = collect_scrape(page_cfg, cfg['keep_keywords'])
    print(page_cfg['name'], '->', len(items))
    for item in items[:10]:
        print(' ', item['title'], '|', item['link'])
    print('---')
