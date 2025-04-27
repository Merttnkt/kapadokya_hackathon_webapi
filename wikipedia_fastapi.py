from fastapi import FastAPI, Query, Path, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import requests
import json
import urllib.parse
import re
import os
from datetime import datetime
import uuid

# OpenAI entegrasyonu
import google.generativeai as genai

app = FastAPI(
    title="Wikipedia API",
    description="Wikipedia'dan içerik çekmek için geliştirilmiş bir API",
    version="1.0.0"
)

class WikipediaService:
    def __init__(self, language="tr"):
        """
        Wikipedia API istemcisi
        :param language: Dil kodu (örn: tr, en, de, fr)
        """
        self.language = language
        self.base_url = f"https://{language}.wikipedia.org/w/api.php"
        self.wiki_url = f"https://{language}.wikipedia.org/wiki/"

    def guide_style_summary(self, title, summary, categories=None, language="tr"):
        prompt = f"""
        Aşağıda Wikipedia'dan alınan bilgilerle, {title} adlı bölgeyi kısaca tanıtan, sade ve bilgilendirici bir metin hazırla:
        Başlık: {title}
        Özet: {summary}
        """
        if categories:
            prompt += f"\nİlgili Kategoriler: {', '.join(categories)}"
        prompt += (
            "\n\nMobil uygulama ekranında gösterilecek şekilde, bölgeyi sade ve bilgilendirici bir dille tanıt."
            "\nBölgenin tarihçesinden ve yakındaki gezilecek önemli yerlerden kısaca bahset."
            "\nÇıktıda satır sonu karakterleri (örn. \\n) veya markdown işaretleri olmasın, metin tek parça halinde düz ve okunabilir olsun."
            "\nMetin minimum 5 maximum 8 cümle uzunluğunda olsun."
            "\nTarafsız, anlaşılır ve doğrudan bilgi veren bir dil kullan."
        )
        try:
            genai.configure(api_key="AIzaSyC8kKgJdV0d-Jn3RmsIYHF5Ksb9quxJRGM")  
            try:
                model = genai.GenerativeModel("models/gemini-pro")
                response = model.generate_content(prompt)
            except Exception:
                model = genai.GenerativeModel("models/gemini-2.5-flash-preview-04-17")
                response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"AI rehber özeti üretilemedi: {e}"
    
    def search(self, query, limit=5, offset=0, categories=None, min_words=300, sort_by="relevance", enrich=True):
        """
        Wikipedia'da arama yapar
        :param query: Arama sorgusu
        :param limit: Sonuç sayısı sınırı
        :param offset: Başlangıç indeksi
        :param categories: Filtrelenecek kategoriler listesi
        :param min_words: Minimum kelime sayısı
        :param sort_by: Sıralama kriteri (relevance, date)
        :return: Arama sonuçları listesi
        """
        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "sroffset": offset,
            "utf8": 1
        }
        # Sıralama kriterini ekle
        if sort_by == "date":
            params["srsort"] = "create_timestamp_desc"
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            raise Exception(f"Wikipedia API isteği başarısız oldu: {e}")
        results = []
        if "query" in data and "search" in data["query"]:
            for result in data["query"]["search"]:
                enriched_result = {
                    "pageid": result["pageid"],
                    "title": result["title"],
                    "snippet": result.get("snippet", "")
                }
                if enrich:
                    try:
                        content = self.get_page_content(result["pageid"])
                        word_count = len(content.split())
                        # İçerik kelime sayısı kontrolü
                        if word_count < min_words:
                            continue
                        categories_list = self.get_page_categories(result["pageid"])
                        # Kategori filtresi kontrolü
                        if categories:
                            # Kullanıcıdan gelen kategorilerle sayfa kategorilerinin kesişimi var mı?
                            if not any(cat.lower() in [c.lower() for c in categories_list] for cat in categories):
                                continue
                        enriched_result["word_count"] = word_count
                        enriched_result["content_summary"] = content[:500] + "..." if len(content) > 500 else content
                        enriched_result["categories"] = categories_list
                        # --- AI rehber özeti ekle ---
                        enriched_result["ai_guide_summary"] = self.guide_style_summary(
                            result["title"],
                            enriched_result["content_summary"],
                            enriched_result["categories"],
                            language=self.language
                        )
                        results.append(enriched_result)
                    except Exception:
                        continue  # Hata olursa bu sonucu atla
                else:
                    results.append(enriched_result)

        return results
    
    def get_page_content(self, page_id):
        """
        Sayfa ID'sine göre tam içerik alır
        :param page_id: Wikipedia sayfa ID'si
        :return: Sayfa içeriği
        """
        # İlk olarak, standart içeriği almaya çalışalım
        params = {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "pageids": page_id,
            "explaintext": 1,
            "exintro": 0    # 0: tam içerik, 1: sadece giriş bölümü
        }
        
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        content = ""
        if "query" in data and "pages" in data["query"]:
            page_data = data["query"]["pages"].get(str(page_id))
            if page_data and "extract" in page_data:
                content = page_data["extract"]
        
        # Eğer içerik kısaysa veya yoksa, bölümleri ayrı ayrı almayı deneyelim
        if not content or len(content) < 1000:
            # Önce sayfa başlığını alalım
            params = {
                "action": "query",
                "format": "json",
                "prop": "info",
                "pageids": page_id,
                "inprop": "url|displaytitle"
            }
            
            response = requests.get(self.base_url, params=params)
            data = response.json()
            
            page_title = ""
            if "query" in data and "pages" in data["query"]:
                page_data = data["query"]["pages"].get(str(page_id))
                if page_data and "title" in page_data:
                    page_title = page_data["title"]
            
            if page_title:
                # Şimdi sayfa bölümlerini alalım
                content = self.get_full_content_by_title(page_title)
        
        return content
    
    def get_full_content_by_title(self, title):
        """
        Başlığa göre tam içerik alır ve bölümleri birleştirir
        :param title: Sayfa başlığı
        :return: Tam sayfa içeriği
        """
        # Önce bölüm yapısını alalım
        params = {
            "action": "parse",
            "format": "json",
            "page": title,
            "prop": "sections"
        }
        
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        full_content = f"# {title}\n\n"
        
        # Ana içeriği alalım (giriş bölümü)
        params = {
            "action": "parse",
            "format": "json",
            "page": title,
            "prop": "text",
            "section": 0,
            "formatversion": 2
        }
        
        response = requests.get(self.base_url, params=params)
        try:
            data = response.json()
            if "parse" in data and "text" in data["parse"]:
                # HTML içeriğini düz metne çevirme girişimi
                content = data["parse"]["text"]
                # HTML etiketlerini kaldırma girişimi
                content = self.html_to_text(content)
                full_content += content + "\n\n"
        except Exception as e:
            full_content += f"Giriş bölümü alınamadı: {str(e)}\n\n"
        
        # Bölümleri alalım
        params = {
            "action": "parse",
            "format": "json",
            "page": title,
            "prop": "sections"
        }
        
        response = requests.get(self.base_url, params=params)
        try:
            data = response.json()
            if "parse" in data and "sections" in data["parse"]:
                for section in data["parse"]["sections"]:
                    section_index = section.get("index", "0")
                    section_title = section.get("line", "")
                    
                    # Referans, Kaynakça gibi bölümleri atlayalım
                    if any(skip_word in section_title.lower() for skip_word in ["kaynakça", "referans", "dipnot", "dış bağlantı", "ayrıca bakınız"]):
                        continue
                    
                    # Her bölümü ayrı ayrı alalım
                    params = {
                        "action": "parse",
                        "format": "json",
                        "page": title,
                        "prop": "text",
                        "section": section_index,
                        "formatversion": 2
                    }
                    
                    section_response = requests.get(self.base_url, params=params)
                    try:
                        section_data = section_response.json()
                        if "parse" in section_data and "text" in section_data["parse"]:
                            section_content = section_data["parse"]["text"]
                            # HTML etiketlerini kaldırma girişimi
                            section_content = self.html_to_text(section_content)
                            
                            if section_content.strip():  # Boş bölümleri atlayalım
                                full_content += f"## {section_title}\n\n{section_content}\n\n"
                    except Exception as e:
                        continue
        except Exception as e:
            full_content += f"Bölümler alınamadı: {str(e)}\n\n"
        
        # Alternatif yöntem: Mobil API kullanarak düz metin almak
        if len(full_content) < 1000:
            try:
                mobile_url = f"https://{self.language}.wikipedia.org/api/rest_v1/page/mobile-sections/{urllib.parse.quote(title)}"
                response = requests.get(mobile_url)
                data = response.json()
                
                # Giriş bölümü
                if "lead" in data and "sections" in data["lead"]:
                    for section in data["lead"]["sections"]:
                        if "text" in section:
                            section_text = self.html_to_text(section["text"])
                            full_content += section_text + "\n\n"
                
                # Diğer bölümler
                if "remaining" in data and "sections" in data["remaining"]:
                    for section in data["remaining"]["sections"]:
                        # Referans, Kaynakça gibi bölümleri atlayalım
                        if "line" in section and any(skip_word in section["line"].lower() for skip_word in ["kaynakça", "referans", "dipnot", "dış bağlantı", "ayrıca bakınız"]):
                            continue
                            
                        if "line" in section:
                            full_content += f"## {section['line']}\n\n"
                        if "text" in section:
                            section_text = self.html_to_text(section["text"])
                            if section_text.strip():  # Boş bölümleri atlayalım
                                full_content += section_text + "\n\n"
            except Exception as e:
                full_content += f"Mobil API üzerinden içerik alınamadı: {str(e)}\n\n"
        
        # Son temizleme
        full_content = self.clean_wiki_content(full_content)
                
        return full_content
    
    def html_to_text(self, html_content):
        """
        HTML içeriğini basit düz metne dönüştürür
        """
        # CSS içeriklerini temizle
        html_content = re.sub(r'<style[^>]*>.*?</style>', ' ', html_content, flags=re.DOTALL)
        
        # CSS sınıf tanımlamalarını temizle
        html_content = re.sub(r'\.mw-parser-output\s+\.[^{]+\{[^}]+\}', ' ', html_content)
        
        # HTML etiketlerini kaldır
        text = re.sub(r'<[^>]+>', ' ', html_content)
        
        # Fazla boşlukları temizle
        text = re.sub(r'\s+', ' ', text)
        
        # HTML karakter kodlarını çöz
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&amp;', '&')
        text = text.replace('&quot;', '"')
        text = text.replace('&apos;', "'")
        
        return text.strip()
    
    def clean_wiki_content(self, content):
        """
        Wikipedia içeriğinden gereksiz metinleri temizler
        """
        # [değiştir | kaynağı değiştir] tarzı metinleri temizle
        content = re.sub(r'\[\s*değiştir\s*\|\s*kaynağı\s*değiştir\s*\]', '', content)
        content = re.sub(r'\[\s*edit\s*\|\s*edit source\s*\]', '', content)
        
        # İçerik düzenleme bağlantılarını temizle
        content = re.sub(r'\(\s*[Dd]üzenle\s*\)', '', content)
        content = re.sub(r'\(\s*[Ee]dit\s*\)', '', content)
        
        # CSS sınıf tanımlarını temizle
        content = re.sub(r'\.mw-parser-output\s+\.[^{]+\{[^}]+\}', '', content)
        
        # Dosya ve medya referanslarını temizle
        content = re.sub(r'Dosya:[^\]]+\]', '', content)
        content = re.sub(r'File:[^\]]+\]', '', content)
        content = re.sub(r'Media:[^\]]+\]', '', content)
        
        # Sayfa referanslarını temizle
        content = re.sub(r'\[\d+\]', '', content)
        
        # Fazla boş satırları temizle
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        return content
    
    def get_page_images(self, page_id):
        """
        Sayfa ID'sine göre resimleri alır
        :param page_id: Wikipedia sayfa ID'si
        :return: Sayfa resimlerinin listesi
        """
        params = {
            "action": "query",
            "format": "json",
            "prop": "images",
            "pageids": page_id
        }
        
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        if "query" in data and "pages" in data["query"]:
            page_data = data["query"]["pages"].get(str(page_id))
            if page_data and "images" in page_data:
                return [img["title"] for img in page_data["images"]]
        return []
    
    def get_image_url(self, image_title):
        """
        Resim başlığına göre resim URL'sini alır
        :param image_title: Resim başlığı (File:örnek.jpg gibi)
        :return: Resim URL'si
        """
        # Dosya başlığından "File:" önekini kaldır
        image_name = image_title.replace("File:", "").replace("Dosya:", "")
        
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "titles": image_title,
            "iiprop": "url"
        }
        
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        if "query" in data and "pages" in data["query"]:
            for page_id, page_data in data["query"]["pages"].items():
                if "imageinfo" in page_data and len(page_data["imageinfo"]) > 0:
                    return page_data["imageinfo"][0]["url"]
        return None
    
    def get_page_categories(self, page_id):
        """
        Sayfa ID'sine göre kategorileri alır
        :param page_id: Wikipedia sayfa ID'si
        :return: Kategori listesi
        """
        params = {
            "action": "query",
            "format": "json",
            "prop": "categories",
            "pageids": page_id,
            "cllimit": 50
        }
        
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        categories = []
        if "query" in data and "pages" in data["query"]:
            page_data = data["query"]["pages"].get(str(page_id))
            if page_data and "categories" in page_data:
                categories = [cat["title"].replace("Kategori:", "").replace("Category:", "") 
                             for cat in page_data["categories"]]
        return categories
    
    def get_page_url(self, title):
        """
        Sayfa başlığından URL oluşturur
        :param title: Sayfa başlığı
        :return: Wikipedia URL'si
        """
        # URL için başlığı kodla
        encoded_title = urllib.parse.quote(title.replace(" ", "_"))
        return f"{self.wiki_url}{encoded_title}"

    def save_results_to_file(self, search_term, results, output_file=None):
        """
        Arama sonuçlarını ve içeriği dosyaya kaydeder
        :param search_term: Arama terimi
        :param results: Arama sonuçları
        :param output_file: Çıktı dosyası adı (None ise otomatik oluşturulur)
        :return: Kaydedilen dosya adı
        """
        if output_file is None:
            # Dosya adını otomatik oluştur
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_search_term = re.sub(r'[^\w\s-]', '', search_term).strip().replace(' ', '_')
            if not safe_search_term:
                safe_search_term = "wiki_search"
            output_file = f"{safe_search_term}_{timestamp}.txt"
        
        # Dosya dizinini kontrol et, yoksa oluştur
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else '.', exist_ok=True)
        
        with open(output_file, "w", encoding="utf-8") as file:
            file.write(f"ARAMA TERİMİ: {search_term}\n")
            file.write("=" * 50 + "\n\n")
            
            if not results:
                file.write("Sonuç bulunamadı.\n")
                return output_file
            
            file.write(f"{len(results)} SONUÇ BULUNDU:\n\n")
            
            for i, result in enumerate(results):
                file.write(f"SONUÇ {i+1}:\n")
                file.write(f"Başlık: {result['title']}\n")
                file.write(f"Sayfa ID: {result['pageid']}\n")
                
                # Sayfa URL'si ekle
                page_url = self.get_page_url(result['title'])
                file.write(f"Sayfa URL: {page_url}\n\n")
                
                # Kategorileri al
                categories = self.get_page_categories(result['pageid'])
                if categories:
                    file.write("KATEGORİLER:\n")
                    file.write(", ".join(categories[:10]))  # İlk 10 kategori
                    file.write("\n\n")
                
                # İçeriği al (genişletilmiş)
                content = self.get_page_content(result['pageid'])
                if content:
                    file.write("İÇERİK:\n")
                    file.write(content)
                    file.write("\n\n")
                else:
                    file.write("İçerik bulunamadı.\n\n")
                
                # Resimleri al
                images = self.get_page_images(result['pageid'])
                if images:
                    file.write("RESİMLER:\n")
                    for j, img in enumerate(images[:5]):  # İlk 5 resmi kaydet
                        img_url = self.get_image_url(img)
                        file.write(f"{j+1}. {img}\n")
                        if img_url:
                            file.write(f"   URL: {img_url}\n")
                    file.write("\n")
                
                file.write("-" * 50 + "\n\n")
        
        return output_file

    def analyze_content(self, page_id, analyze_type="summary"):
        """
        Sayfa içeriğini analiz eder
        :param page_id: Wikipedia sayfa ID'si
        :param analyze_type: Analiz tipi (summary, keywords, sentiment)
        :return: Analiz sonucu
        """
        content = self.get_page_content(page_id)
        
        if not content:
            return {"error": "İçerik bulunamadı"}
        
        result = {}
        
        # Özet çıkarma
        if analyze_type == "summary" or analyze_type == "all":
            # Basit bir özet algoritması - ilk 500 karakter
            summary = content.split("\n\n")[0]
            if len(summary) > 500:
                summary = summary[:497] + "..."
            result["summary"] = summary
        
        # Anahtar kelimeler
        if analyze_type == "keywords" or analyze_type == "all":
            # Basit bir anahtar kelime çıkarma yöntemi
            words = re.findall(r'\b[a-zA-ZğüşıöçĞÜŞİÖÇ]{4,}\b', content.lower())
            word_count = {}
            for word in words:
                if word not in ["için", "olarak", "kadar", "sonra", "önce", "daha", "diğer"]:
                    word_count[word] = word_count.get(word, 0) + 1
            
            # En çok geçen 10 kelimeyi al
            keywords = sorted(word_count.items(), key=lambda x: x[1], reverse=True)[:10]
            result["keywords"] = {k: v for k, v in keywords}
        
        # Bölüm başlıkları
        if analyze_type == "sections" or analyze_type == "all":
            sections = re.findall(r'## (.*?)\n', content)
            result["sections"] = sections
        
        return result

    def compare_pages(self, page_id_1, page_id_2):
        """
        İki sayfayı karşılaştırır
        :param page_id_1: İlk sayfa ID'si
        :param page_id_2: İkinci sayfa ID'si
        :return: Karşılaştırma sonucu
        """
        # İlk sayfa bilgilerini al
        params = {
            "action": "query",
            "format": "json",
            "prop": "info|categories",
            "pageids": page_id_1,
            "inprop": "url|displaytitle",
            "cllimit": 50
        }
        
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        page1_info = {}
        if "query" in data and "pages" in data["query"]:
            page_data = data["query"]["pages"].get(str(page_id_1))
            if page_data:
                page1_info["title"] = page_data.get("title", "")
                page1_info["url"] = page_data.get("fullurl", "")
                page1_info["categories"] = [cat["title"].replace("Kategori:", "").replace("Category:", "") 
                                          for cat in page_data.get("categories", [])]
        
        # İkinci sayfa bilgilerini al
        params["pageids"] = page_id_2
        response = requests.get(self.base_url, params=params)
        data = response.json()
        
        page2_info = {}
        if "query" in data and "pages" in data["query"]:
            page_data = data["query"]["pages"].get(str(page_id_2))
            if page_data:
                page2_info["title"] = page_data.get("title", "")
                page2_info["url"] = page_data.get("fullurl", "")
                page2_info["categories"] = [cat["title"].replace("Kategori:", "").replace("Category:", "") 
                                          for cat in page_data.get("categories", [])]
        
        # İçerikleri al
        page1_info["content"] = self.get_page_content(page_id_1)
        page2_info["content"] = self.get_page_content(page_id_2)
        
        # Ortak kategorileri bul
        common_categories = list(set(page1_info["categories"]) & set(page2_info["categories"]))
        
        # Benzerlik hesaplama (basit kelime benzerliği)
        words1 = set(re.findall(r'\b[a-zA-ZğüşıöçĞÜŞİÖÇ]{4,}\b', page1_info["content"].lower()))
        words2 = set(re.findall(r'\b[a-zA-ZğüşıöçĞÜŞİÖÇ]{4,}\b', page2_info["content"].lower()))
        
        common_words = words1 & words2
        similarity = len(common_words) / max(len(words1), len(words2)) if max(len(words1), len(words2)) > 0 else 0
        
        return {
            "page1": {
                "title": page1_info["title"],
                "url": page1_info["url"],
                "categories": page1_info["categories"]
            },
            "page2": {
                "title": page2_info["title"],
                "url": page2_info["url"],
                "categories": page2_info["categories"]
            },
            "common_categories": common_categories,
            "similarity": similarity,
            "common_word_count": len(common_words)
        }


# ----- FastAPI Modelleri -----

class SearchParams(BaseModel):
    query: str = Field(..., description="Arama sorgusu")
    language: str = Field("tr", description="Dil kodu (örn: tr, en, de)")
    limit: int = Field(10, ge=1, le=50, description="Sonuç sayısı sınırı")
    offset: int = Field(0, ge=0, description="Başlangıç indeksi")
    categories: Optional[List[str]] = Field(None, description="Filtrelenecek kategoriler")
    min_words: int = Field(0, ge=0, description="Minimum kelime sayısı")
    sort_by: str = Field("relevance", description="Sıralama kriteri (relevance, date)")
    output_file: Optional[str] = Field(None, description="Çıktı dosya adı (belirtilmezse otomatik oluşturulur)")

class AnalyzeParams(BaseModel):
    page_id: int = Field(..., description="Wikipedia sayfa ID'si")
    analyze_type: str = Field("summary", description="Analiz tipi (summary, keywords, sections, all)")

class CompareParams(BaseModel):
    page_id_1: int = Field(..., description="İlk sayfa ID'si")
    page_id_2: int = Field(..., description="İkinci sayfa ID'si")

class SearchResponse(BaseModel):
    search_term: str
    results_count: int
    results: List[Dict[str, Any]]
    output_file: Optional[str] = None

# ----- FastAPI Endpoint'leri -----

@app.get("/")
async def root():
    return {"message": "Wikipedia API'ye hoş geldiniz!"}

@app.post("/search", response_model=SearchResponse)
async def search_wikipedia(params: SearchParams):
    """
    Wikipedia'da arama yapar ve sonuçları döndürür.
    İsteğe bağlı olarak sonuçları dosyaya kaydeder.
    """
    wiki_service = WikipediaService(language=params.language)
    results = wiki_service.search(
        query=params.query,
        limit=params.limit,
        offset=params.offset,
        categories=params.categories,
        min_words=params.min_words,
        sort_by=params.sort_by
    )
    
    output_file = None
    if results:
        output_file = wiki_service.save_results_to_file(params.query, results, params.output_file)
    
    return {
        "search_term": params.query,
        "results_count": len(results),
        "results": results,
        "output_file": output_file
    }

@app.get("/page/{page_id}", response_model=Dict[str, Any])
async def get_page(
    page_id: int = Path(..., description="Wikipedia sayfa ID'si")
):
    """
    Wikipedia sayfasının tam içeriğini döndürür
    """
    wiki_service = WikipediaService()
    content = wiki_service.get_page_content(page_id)
    categories = wiki_service.get_page_categories(page_id)
    
    if not content:
        raise HTTPException(status_code=404, detail="Sayfa bulunamadı")
    
    # Sayfa başlığını almak için
    params = {
        "action": "query",
        "format": "json",
        "prop": "info",
        "pageids": page_id,
        "inprop": "url|displaytitle"
    }
    
    response = requests.get(wiki_service.base_url, params=params)
    data = response.json()
    
    title = ""
    url = ""
    if "query" in data and "pages" in data["query"]:
        page_data = data["query"]["pages"].get(str(page_id))
        if page_data:
            title = page_data.get("title", "")
            url = page_data.get("fullurl", "")
    
    return {
        "page_id": page_id,
        "title": title,
        "url": url,
        "categories": categories,
        "content": content,
        "word_count": len(content.split()) if content else 0
    }

@app.post("/analyze", response_model=Dict[str, Any])
async def analyze_page(params: AnalyzeParams):
    """
    Wikipedia sayfasının içeriğini analiz eder
    """
wiki_service = WikipediaService()

def analyze_content(params):
    result = wiki_service.analyze_content(params.page_id, params.analyze_type)
    
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    
    return result

@app.post("/compare", response_model=Dict[str, Any])
async def compare_pages(params: CompareParams):
    """
    İki Wikipedia sayfasını karşılaştırır
    """
    wiki_service = WikipediaService()
    result = wiki_service.compare_pages(params.page_id_1, params.page_id_2)
    
    return result

@app.get("/download/{filename}")
async def download_file(filename: str):
    """
    Belirtilen dosyayı indirme endpoint'i
    """
    if not os.path.exists(filename):
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    
    return FileResponse(path=filename, filename=filename, media_type="text/plain")

@app.get("/categories/{page_id}", response_model=List[str])
async def get_categories(page_id: int):
    """
    Belirtilen sayfanın kategorilerini döndürür
    """
    wiki_service = WikipediaService()
    categories = wiki_service.get_page_categories(page_id)
    
    return categories

@app.get("/images/{page_id}", response_model=List[Dict[str, str]])
async def get_images(page_id: int):
    """
    Belirtilen sayfanın resimlerini döndürür
    """
    wiki_service = WikipediaService()
    images = wiki_service.get_page_images(page_id)
    
    image_data = []
    for img in images:
        url = wiki_service.get_image_url(img)
        if url:
            image_data.append({
                "title": img,
                "url": url
            })
    
    return image_data

@app.get("/related/{page_id}", response_model=List[Dict[str, Any]])
async def get_related_pages(
    page_id: int,
    limit: int = Query(5, ge=1, le=20)
):
    """
    Belirtilen sayfayla ilgili diğer sayfaları döndürür
    """
    wiki_service = WikipediaService()
    
    # Önce sayfa kategorilerini alalım
    categories = wiki_service.get_page_categories(page_id)
    
    if not categories:
        return []
    
    # Sayfa başlığını alalım
    params = {
        "action": "query",
        "format": "json",
        "prop": "info",
        "pageids": page_id,
        "inprop": "url|displaytitle"
    }
    
    response = requests.get(wiki_service.base_url, params=params)
    data = response.json()
    
    title = ""
    if "query" in data and "pages" in data["query"]:
        page_data = data["query"]["pages"].get(str(page_id))
        if page_data:
            title = page_data.get("title", "")
    
    # İlgili sayfaları bulmak için kategori tabanlı bir sorgu oluşturalım
    # En ilgili kategoriden bir tane seçelim
    if categories:
        main_category = categories[0]
        
        # Kategoriye ait sayfaları alalım
        params = {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": f"Kategori:{main_category}",
            "cmlimit": limit + 1,  # Kendisi de listede olabilir
            "cmtype": "page"
        }
        
        response = requests.get(wiki_service.base_url, params=params)
        data = response.json()
        
        related_pages = []
        if "query" in data and "categorymembers" in data["query"]:
            for member in data["query"]["categorymembers"]:
                # Kendisini hariç tutalım
                if member["pageid"] != page_id:
                    related_pages.append({
                        "title": member["title"],
                        "page_id": member["pageid"],
                        "url": wiki_service.get_page_url(member["title"])
                    })
                    
                    if len(related_pages) >= limit:
                        break
        
        return related_pages
    
    return []

@app.get("/advanced-search", response_model=Dict[str, Any])
async def advanced_search(
    query: str = Query(..., description="Arama sorgusu"),
    language: str = Query("tr", description="Dil kodu"),
    exact_phrase: Optional[str] = Query(None, description="Tam olarak bu cümle"),
    exclude_words: Optional[str] = Query(None, description="Bu kelimeleri içermeyen"),
    date_start: Optional[str] = Query(None, description="Başlangıç tarihi (YYYY-MM-DD)"),
    date_end: Optional[str] = Query(None, description="Bitiş tarihi (YYYY-MM-DD)"),
    category: Optional[str] = Query(None, description="Kategori"),
    min_words: int = Query(0, ge=0, description="Minimum kelime sayısı"),
    limit: int = Query(10, ge=1, le=50, description="Sonuç sınırı")
):
    """
    Gelişmiş arama seçenekleri sunar
    """
    wiki_service = WikipediaService(language=language)
    
    # Gelişmiş sorgu oluştur
    advanced_query = query
    
    if exact_phrase:
        advanced_query += f' "{exact_phrase}"'
    
    if exclude_words:
        for word in exclude_words.split():
            advanced_query += f" -{word}"
    
    if date_start or date_end:
        date_range = ""
        if date_start:
            date_range += date_start
        date_range += "/"
        if date_end:
            date_range += date_end
        
        if date_range != "/":
            advanced_query += f" {date_range}"
    
    # Temel aramayı yap
    results = wiki_service.search(
        query=advanced_query,
        limit=limit,
        min_words=min_words
    )
    
    # Kategori filtresi uygula (eğer belirtilmişse)
    if category and results:
        filtered_results = []
        for result in results:
            result_categories = wiki_service.get_page_categories(result["pageid"])
            if any(category.lower() in cat.lower() for cat in result_categories):
                filtered_results.append(result)
        results = filtered_results
    
    # Dosya adını otomatik oluştur
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_query = re.sub(r'[^\w\s-]', '', query).strip().replace(' ', '_')
    if not safe_query:
        safe_query = "wiki_search"
    output_file = f"advanced_{safe_query}_{timestamp}.txt"
    
    if results:
        output_file = wiki_service.save_results_to_file(advanced_query, results, output_file)
    
    return {
        "query": advanced_query,
        "original_query": query,
        "results_count": len(results),
        "results": results,
        "output_file": output_file if results else None
    }

@app.get("/topic-search", response_model=Dict[str, Any])
async def topic_search(
    topic: str = Query(..., description="Araştırılacak konu"),
    depth: int = Query(2, ge=1, le=3, description="Araştırma derinliği"),
    language: str = Query("tr", description="Dil kodu"),
    limit: int = Query(5, ge=1, le=10, description="Ana başlık sayısı")
):
    """
    Belirli bir konu hakkında derinlemesine araştırma yapar.
    Ana sayfaları ve bağlantılı alt konuları araştırır.
    """
    wiki_service = WikipediaService(language=language)
    
    # Ana sayfaları bul
    main_results = wiki_service.search(query=topic, limit=limit)
    
    if not main_results:
        return {
            "topic": topic,
            "main_pages": [],
            "related_topics": [],
            "output_file": None
        }
    
    main_pages = []
    related_topics = []
    all_results = []
    
    # Her bir ana sayfa için
    for result in main_results:
        page_id = result["pageid"]
        title = result["title"]
        
        page_content = wiki_service.get_page_content(page_id)
        categories = wiki_service.get_page_categories(page_id)
        url = wiki_service.get_page_url(title)
        
        main_page = {
            "title": title,
            "page_id": page_id,
            "url": url,
            "categories": categories[:5],  # İlk 5 kategori
            "summary": page_content.split("\n\n")[0] if page_content else ""
        }
        
        main_pages.append(main_page)
        all_results.append(result)
        
        # Alt konuları (bağlantılı sayfaları) bul (derinlik 1)
        if depth >= 2:
            params = {
                "action": "query",
                "format": "json",
                "prop": "links",
                "pageids": page_id,
                "plnamespace": 0,
                "pllimit": 10
            }
            
            response = requests.get(wiki_service.base_url, params=params)
            data = response.json()
            
            related_page_titles = []
            if "query" in data and "pages" in data["query"]:
                page_data = data["query"]["pages"].get(str(page_id))
                if page_data and "links" in page_data:
                    for link in page_data["links"]:
                        related_page_titles.append(link["title"])
            
            # Her bir bağlantılı başlık için arama yap
            for related_title in related_page_titles[:3]:  # İlk 3 bağlantılı başlık
                related_results = wiki_service.search(query=related_title, limit=1)
                
                if related_results:
                    related_result = related_results[0]
                    related_id = related_result["pageid"]
                    
                    related_content = wiki_service.get_page_content(related_id)
                    related_url = wiki_service.get_page_url(related_title)
                    
                    related_topic = {
                        "title": related_title,
                        "page_id": related_id,
                        "url": related_url,
                        "summary": related_content.split("\n\n")[0] if related_content else "",
                        "main_topic": title
                    }
                    
                    related_topics.append(related_topic)
                    all_results.append(related_result)
    
    # Dosya adını otomatik oluştur
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_topic = re.sub(r'[^\w\s-]', '', topic).strip().replace(' ', '_')
    if not safe_topic:
        safe_topic = "topic_search"
    output_file = f"topic_{safe_topic}_{timestamp}.txt"
    
    if all_results:
        output_file = wiki_service.save_results_to_file(f"Konu Araştırması: {topic}", all_results, output_file)
    
    return {
        "topic": topic,
        "main_pages": main_pages,
        "related_topics": related_topics,
        "output_file": output_file
    }

# Uygulamayı çalıştırma
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)