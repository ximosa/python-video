import streamlit as st
import os
import json
import logging
import time
import io
from google.cloud import texttospeech
from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import googleapiclient.discovery
import googleapiclient.errors
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import google_auth_oauthlib.flow

logging.basicConfig(level=logging.INFO)

# Cargar credenciales de GCP desde secrets
credentials = dict(st.secrets.gcp_service_account)
with open("google_credentials.json", "w") as f:
    json.dump(credentials, f)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_credentials.json"

# Cargar credenciales de YouTube desde secrets
youtube_creds = st.secrets["youtube_credentials"]
client_id = youtube_creds["client_id"]
client_secret = youtube_creds["client_secret"]
auth_uri = youtube_creds["auth_uri"]
token_uri = youtube_creds["token_uri"]
auth_provider_x509_cert_url = youtube_creds["auth_provider_x509_cert_url"]
redirect_uris = youtube_creds["redirect_uris"]

print(f"Client ID: {client_id}")
print(f"Client Secret: {client_secret}")

# Configuración de voces
VOCES_DISPONIBLES = {
    'es-ES-Journey-D': texttospeech.SsmlVoiceGender.MALE,
    'es-ES-Journey-F': texttospeech.SsmlVoiceGender.FEMALE,
    'es-ES-Journey-O': texttospeech.SsmlVoiceGender.FEMALE,
    'es-ES-Neural2-A': texttospeech.SsmlVoiceGender.FEMALE,
    'es-ES-Neural2-B': texttospeech.SsmlVoiceGender.MALE,
    'es-ES-Neural2-C': texttospeech.SsmlVoiceGender.FEMALE,
    'es-ES-Neural2-D': texttospeech.SsmlVoiceGender.FEMALE,
    'es-ES-Neural2-E': texttospeech.SsmlVoiceGender.FEMALE,
    'es-ES-Neural2-F': texttospeech.SsmlVoiceGender.MALE,
    'es-ES-Polyglot-1': texttospeech.SsmlVoiceGender.MALE,
    'es-ES-Standard-A': texttospeech.SsmlVoiceGender.FEMALE,
    'es-ES-Standard-B': texttospeech.SsmlVoiceGender.MALE,
    'es-ES-Standard-C': texttospeech.SsmlVoiceGender.FEMALE
}

# Funcion de creacion de texto
def create_text_image(text, size=(1280, 360), font_size=30, line_height=40):
    img = Image.new('RGB', size, 'black')
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)

    words = text.split()
    lines = []
    current_line = []

    for word in words:
        current_line.append(word)
        test_line = ' '.join(current_line)
        left, top, right, bottom = draw.textbbox((0, 0), test_line, font=font)
        if right > size[0] - 60:
            current_line.pop()
            lines.append(' '.join(current_line))
            current_line = [word]
    lines.append(' '.join(current_line))

    total_height = len(lines) * line_height
    y = (size[1] - total_height) // 2

    for line in lines:
        left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
        x = (size[0] - (right - left)) // 2
        draw.text((x, y), line, font=font, fill="white")
        y += line_height

    return np.array(img)

# Funcion de creacion de video
def create_simple_video(texto, nombre_salida, voz):
    clips_audio = []
    clips_finales = []
    archivos_temp = []
    try:
        logging.info("Iniciando proceso de creación de video...")
        frases = [f.strip() + "." for f in texto.split('.') if f.strip()]
        client = texttospeech.TextToSpeechClient()
        
        tiempo_acumulado = 0
        
        # Agrupamos frases en segmentos
        segmentos_texto = []
        segmento_actual = ""
        for frase in frases:
          if len(segmento_actual) + len(frase) < 300:
            segmento_actual += " " + frase
          else:
            segmentos_texto.append(segmento_actual.strip())
            segmento_actual = frase
        segmentos_texto.append(segmento_actual.strip())
        
        for i, segmento in enumerate(segmentos_texto):
            logging.info(f"Procesando segmento {i+1} de {len(segmentos_texto)}")
            
            synthesis_input = texttospeech.SynthesisInput(text=segmento)
            voice = texttospeech.VoiceSelectionParams(
                language_code="es-ES",
                name=voz,
                ssml_gender=VOCES_DISPONIBLES[voz]
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )
            
            retry_count = 0
            max_retries = 3
            
            while retry_count <= max_retries:
              try:
                response = client.synthesize_speech(
                    input=synthesis_input,
                    voice=voice,
                    audio_config=audio_config
                )
                break
              except Exception as e:
                  logging.error(f"Error al solicitar audio (intento {retry_count + 1}): {str(e)}")
                  if "429" in str(e):
                    retry_count +=1
                    time.sleep(2**retry_count)
                  else:
                    raise
            
            if retry_count > max_retries:
                raise Exception("Maximos intentos de reintento alcanzado")
            
            temp_filename = f"temp_audio_{i}.mp3"
            archivos_temp.append(temp_filename)
            with open(temp_filename, "wb") as out:
                out.write(response.audio_content)
            
            audio_clip = AudioFileClip(temp_filename)
            clips_audio.append(audio_clip)
            duracion = audio_clip.duration
            
            text_img = create_text_image(segmento)
            txt_clip = (ImageClip(text_img)
                      .set_start(tiempo_acumulado)
                      .set_duration(duracion)
                      .set_position('center'))
            
            video_segment = txt_clip.set_audio(audio_clip.set_start(tiempo_acumulado))
            clips_finales.append(video_segment)
            
            tiempo_acumulado += duracion
            time.sleep(0.2)

        # Añadir clip de suscripción
        subscribe_text = "¡SUSCRÍBETE AL CANAL!\n👍 Dale like y activa la campana 🔔"
        subscribe_img = create_text_image(subscribe_text, font_size=40)
        duracion_subscribe = 5

        subscribe_clip = (ImageClip(subscribe_img)
                        .set_start(tiempo_acumulado)
                        .set_duration(duracion_subscribe)
                        .set_position('center'))

        clips_finales.append(subscribe_clip)
        
        video_final = concatenate_videoclips(clips_finales, method="compose")
        
        video_buffer = io.BytesIO()
        video_final.write_videofile(
            video_buffer,
            format='mp4',
            fps=24,
            codec='libx264',
            audio_codec='aac',
            preset='ultrafast',
            threads=4,
        )
        video_buffer.seek(0)

        video_final.close()
        
        for clip in clips_audio:
            clip.close()
        
        for clip in clips_finales:
            clip.close()

        for temp_file in archivos_temp:
            try:
                if os.path.exists(temp_file):
                    os.close(os.open(temp_file, os.O_RDONLY))
                    os.remove(temp_file)
            except:
                pass
        
        return True, video_buffer, "Video generado exitosamente"
        
    except Exception as e:
        logging.error(f"Error: {str(e)}")
        for clip in clips_audio:
            try:
                clip.close()
            except:
                pass
                
        for clip in clips_finales:
            try:
                clip.close()
            except:
                pass
        
        for temp_file in archivos_temp:
            try:
                if os.path.exists(temp_file):
                    os.close(os.open(temp_file, os.O_RDONLY))
                    os.remove(temp_file)
            except:
                pass
        
        return False, None, str(e)


# Funcionalidad para obtener las credenciales de YouTube
def get_youtube_creds():
    """Obtiene y gestiona las credenciales de YouTube."""
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    credentials_path = "credentials.json"
    creds = None
    
    if os.path.exists(credentials_path):
        try:
            creds = Credentials.from_authorized_user_file(credentials_path, SCOPES)
        except ValueError as e:
            print(f"Error al cargar credenciales: {e}. Eliminando el archivo de credenciales.")
            os.remove(credentials_path)
            creds = None  # Forzar la creación de nuevas credenciales
        except Exception as e:
            print(f"Error al cargar credenciales: {e}. Intenta ejecutar la aplicación nuevamente")
            return None
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Error al refrescar las credenciales: {e}. Se requiere nueva autenticación.")
                os.remove(credentials_path)
                creds = None
        if not creds:
            try:
                # El flujo debe estar en formato "web" y las redirect uris deben de concordar
                flow = google_auth_oauthlib.flow.Flow.from_client_config(
                    {
                    "web":{
                        "client_id": client_id,
                        "project_id": st.secrets["youtube_credentials"]["project_id"],
                        "auth_uri": auth_uri,
                        "token_uri": token_uri,
                        "auth_provider_x509_cert_url": auth_provider_x509_cert_url,
                        "client_secret": client_secret,
                        "redirect_uris": redirect_uris
                        }
                    },
                    scopes = SCOPES)
                
                auth_url, _ = flow.authorization_url(prompt='consent')
                st.session_state['auth_url'] = auth_url
                
                st.write(f'Abre este enlace para autorizar la aplicacion: {auth_url}')
                auth_code = st.text_input("Introduce el código de autorización:")
                
                if auth_code:
                    token = flow.fetch_token(code = auth_code)
                    creds = Credentials.from_authorized_user_info(token,SCOPES)
                    
                    with open(credentials_path, 'w') as token_file:
                        token_file.write(creds.to_json())
                    
            except Exception as e:
                print(f"Error durante el flujo de autorización: {e}")
                return None
    return creds

# Funcionalidad para subir a YouTube
def upload_video(video_bytes, title, description):
    """Sube un video a YouTube."""
    API_SERVICE_NAME = "youtube"
    API_VERSION = "v3"
    
    creds = get_youtube_creds()
    
    if not creds:
        print("No se pudieron obtener las credenciales de YouTube.")
        return False, "No se pudieron obtener las credenciales de YouTube."
    
    try:
        youtube = googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=creds)
        body = {
            'snippet': {
                'title': title,
                'description': description,
                'categoryId': 22  # Categoría "People & Blogs"
            },
            'status': {
                'privacyStatus': 'public'  # O "unlisted" o "private"
            }
        }

        # Subir el video
        try:
            media_body = googleapiclient.http.MediaIoBaseUpload(video_bytes, mimetype='video/mp4',resumable=True)
            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media_body
            )

            response = request.execute()

            print(f"Video subido con éxito. ID: {response['id']}")
            return True, response['id']
        except googleapiclient.errors.HttpError as e:
            print(f"Error al subir el video: {e}")
            return False, str(e)
    except Exception as e:
        print(f"Error desconocido al subir el vídeo: {e}")
        return False, str(e)


def main():
    st.title("Creador de Videos Automático")
    
    uploaded_file = st.file_uploader("Carga un archivo de texto", type="txt")
    voz_seleccionada = st.selectbox("Selecciona la voz", options=list(VOCES_DISPONIBLES.keys()))
    
    if uploaded_file:
        texto = uploaded_file.read().decode("utf-8")
        nombre_salida = st.text_input("Nombre del Video (sin extensión)", "video_generado")
        
        if st.button("Generar Video"):
            with st.spinner('Generando video...'):
                success, video_bytes, message = create_simple_video(texto, nombre_salida, voz_seleccionada)
                if success:
                  st.success(message)
                  st.video(video_bytes)
                  st.download_button(label="Descargar video",data=video_bytes,file_name=f"{nombre_salida}.mp4")
                    
                  # Guardamos el video_bytes en session_state
                  st.session_state.video_bytes = video_bytes
                else:
                  st.error(f"Error al generar video: {message}")

        # Mostramos el boton de Subir solo si el video se ha generado correctamente
        if st.session_state.get("video_bytes"):
            if st.button("Subir video a Youtube"):
                descripcion = texto[:200]
                video_bytes = st.session_state.video_bytes
                with st.spinner('Subiendo video a youtube...'):
                    upload_success, upload_message = upload_video(video_bytes,nombre_salida,descripcion)
                    if upload_success:
                        st.success(f"Video subido exitosamente a youtube. ID: {upload_message}")
                    else:
                        st.error(f"Error al subir a youtube: {upload_message}")

if __name__ == "__main__":
    # Inicializar session state
    if "video_bytes" not in st.session_state:
        st.session_state.video_bytes = None
    if 'auth_url' not in st.session_state:
        st.session_state['auth_url'] = None
    main()
