import streamlit as st
import os
import json
import logging
import time
from google.cloud import texttospeech
from moviepy.editor import AudioFileClip, ImageClip, CompositeVideoClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
import tempfile

logging.basicConfig(level=logging.INFO)

# Cargar credenciales de GCP desde secrets
credentials = dict(st.secrets.gcp_service_account)
with open("google_credentials.json", "w") as f:
    json.dump(credentials, f)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_credentials.json"

# Cargar credenciales de Youtube desde secrets
youtube_credentials = dict(st.secrets.youtube_web_credentials)
with open("youtube_web_credentials.json", "w") as f:
    json.dump(youtube_credentials, f)

youtube_credentials_path = "youtube_web_credentials.json"

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
    archivos_temp = []
    clips_audio = []
    clips_finales = []
    
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
        
        video_final.write_videofile(
            nombre_salida,
            fps=24,
            codec='libx264',
            audio_codec='aac',
            preset='ultrafast',
            threads=4
        )
        
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
        
        return True, "Video generado exitosamente"
        
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
        
        return False, str(e)


# Funcionalidad para subir a YouTube
def upload_video(file_path, title, description, credentials_path):
    """Sube un video a YouTube."""

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    API_SERVICE_NAME = "youtube"
    API_VERSION = "v3"

# Autenticación
flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
credentials_path, SCOPES, redirect_uri='http://localhost')
credentials = flow.run_local_server(port=0)
    youtube = googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials=credentials)

    # Configuración del video
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
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=googleapiclient.http.MediaFileUpload(file_path)
        )
        response = request.execute()

        print(f"Video subido con éxito. ID: {response['id']}")
        return True, response['id']
    except googleapiclient.errors.HttpError as e:
        print(f"Error al subir el video: {e}")
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
            nombre_salida_completo = f"{nombre_salida}.mp4"
            success, message = create_simple_video(texto, nombre_salida_completo, voz_seleccionada)
            if success:
              st.success(message)
              st.video(nombre_salida_completo)
              with open(nombre_salida_completo, 'rb') as file:
                st.download_button(label="Descargar video",data=file,file_name=nombre_salida_completo)

              # Usamos un st.session_state para controlar si el video se ha generado
              st.session_state.video_generado = True
            else:
              st.error(f"Error al generar video: {message}")
              st.session_state.video_generado = False

      # Mostramos el boton de Subir solo si el video se ha generado correctamente
      if st.session_state.get("video_generado", False):
        if st.button("Subir video a Youtube"):
            descripcion = texto[:200]
            nombre_salida_completo = f"{nombre_salida}.mp4"
            with st.spinner('Subiendo video a youtube...'):
                upload_success, upload_message = upload_video(nombre_salida_completo,nombre_salida,descripcion, youtube_credentials_path)
                if upload_success:
                    st.success(f"Video subido exitosamente a youtube. ID: {upload_message}")
                else:
                    st.error(f"Error al subir a youtube: {upload_message}")
    
if __name__ == "__main__":
    # Inicializar session state
    if "video_generado" not in st.session_state:
      st.session_state.video_generado = False
    main()
