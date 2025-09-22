import subprocess
import os
import sys
from tqdm import tqdm
def ffmpeg_mute_cmd(input_path, output_path):
    command = [
        "ffmpeg",
        "-i", input_path,
        "-c:v", "copy",  
        "-an",
        output_path
    ]
    # command = [
    #     "ffmpeg",
    #     "-i", input_path,
    #     "-an", 
    #     "-vcodec", "copy",
    #     output_path
    # ]

    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # subprocess.run(command, check=True)

        print(f"Video muted and saved to {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")


def mute_video(video_folder, extension = ('.mp4', '.avi', '.mov', '.mkv')):
    if not os.path.exists(video_folder):
        print(f"Error: The directory {video_folder} does not exist.")
        return

    output_folder = os.path.join(video_folder, 'muted_videos')
    os.makedirs(output_folder, exist_ok=True)

    for filename in tqdm(os.listdir(video_folder), desc="Muting videos..."):
        # print(filename)
        if filename.lower().endswith(extension):
            input_path = os.path.join(video_folder, filename)
            output_path = os.path.join(output_folder, filename)
            ffmpeg_mute_cmd(input_path, output_path)

if __name__ == "__main__":
    video_folder = r'H:\DCIM\Movie'
    mute_video(video_folder)