; Inno Setup Script for Tf2SkinGenerator
; Bootstrap installer that downloads the full package from GitHub Releases
; Version WITHOUT IDP - uses PowerShell for downloading

#define AppName "Tf2SkinGenerator"
#define AppVersion "1.0.0"
#define AppPublisher "xietyBTW"
#define AppURL "https://github.com/xietyBTW/Tf2SkinGenerator"
#define RepoOwner "xietyBTW"
#define RepoName "Tf2SkinGenerator"
#define AssetName "Tf2SkinGenerator-windows.zip"
#define DownloadURL "https://github.com/{#RepoOwner}/{#RepoName}/releases/latest/download/{#AssetName}"

[Setup]
AppId={{A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
PrivilegesRequired=lowest
OutputBaseFilename={#AppName}-Setup
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
SetupIconFile=
DisableProgramGroupPage=no
DisableWelcomePage=no
WizardImageFile=compiler:WizModernImage-IS.bmp
WizardSmallImageFile=compiler:WizModernSmallImage-IS.bmp

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1

[Code]
var
  DownloadProgressPage: TOutputProgressWizardPage;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard();
begin
  DownloadProgressPage := CreateOutputProgressPage('Скачивание', 'Скачивание файлов приложения...');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ZipPath: String;
  DownloadCommand: String;
  DownloadArgs: String;
  UnzipCommand: String;
  UnzipArgs: String;
  ExitCode: Integer;
  ErrorCode: Integer;
begin
  Result := True;
  
  if CurPageID = wpReady then
  begin
    ZipPath := ExpandConstant('{tmp}\{#AssetName}');
    
    // Удаляем старый файл если существует
    if FileExists(ZipPath) then
      DeleteFile(ZipPath);
    
    // Скачивание через PowerShell Invoke-WebRequest
    DownloadProgressPage.SetText('Скачивание файлов приложения...', '');
    DownloadProgressPage.Show;
    try
      DownloadProgressPage.SetProgress(0, 100);
      
      DownloadCommand := 'powershell.exe';
      DownloadArgs := Format('-NoProfile -ExecutionPolicy Bypass -Command "try { $ProgressPreference = ''SilentlyContinue''; Invoke-WebRequest -Uri ''%s'' -OutFile ''%s'' -UseBasicParsing; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"', [
        'https://github.com/{#RepoOwner}/{#RepoName}/releases/latest/download/{#AssetName}',
        ZipPath
      ]);
      
      Log('Downloading archive with PowerShell...');
      Log('URL: https://github.com/{#RepoOwner}/{#RepoName}/releases/latest/download/{#AssetName}');
      Log('Save to: ' + ZipPath);
      
      if not Exec(DownloadCommand, DownloadArgs, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      begin
        DownloadProgressPage.Hide;
        MsgBox('Ошибка при запуске PowerShell для скачивания файла.', mbError, MB_OK);
        Result := False;
        Exit;
      end;
      
      if ExitCode <> 0 then
      begin
        DownloadProgressPage.Hide;
        MsgBox(Format('Ошибка при скачивании файла. Код выхода PowerShell: %d'#13#10'Проверьте подключение к интернету и попробуйте снова.', [ExitCode]), mbError, MB_OK);
        Result := False;
        Exit;
      end;
      
      // Проверка что файл скачан
      if not FileExists(ZipPath) then
      begin
        DownloadProgressPage.Hide;
        MsgBox('Ошибка: скачанный файл не найден: ' + ZipPath, mbError, MB_OK);
        Result := False;
        Exit;
      end;
      
      DownloadProgressPage.SetProgress(50, 100);
      DownloadProgressPage.SetText('Скачивание завершено.', 'Распаковка файлов...');
      
      // Распаковка через PowerShell Expand-Archive
      UnzipCommand := 'powershell.exe';
      UnzipArgs := Format('-NoProfile -ExecutionPolicy Bypass -Command "$tmpDir = Join-Path $env:TEMP ''Tf2SkinGenerator-install''; if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }; Expand-Archive -Path ''%s'' -DestinationPath $tmpDir -Force; $sourceDir = Join-Path $tmpDir ''Tf2SkinGenerator''; if (Test-Path $sourceDir) { Copy-Item -Path ''$sourceDir\*'' -Destination ''%s'' -Recurse -Force; Remove-Item -Recurse -Force $tmpDir } else { Copy-Item -Path ''$tmpDir\*'' -Destination ''%s'' -Recurse -Force; Remove-Item -Recurse -Force $tmpDir }"', [
        ZipPath,
        ExpandConstant('{app}'),
        ExpandConstant('{app}')
      ]);
      
      Log('Extracting archive with PowerShell...');
      
      if not Exec(UnzipCommand, UnzipArgs, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      begin
        DownloadProgressPage.Hide;
        MsgBox('Ошибка при запуске PowerShell для распаковки архива.', mbError, MB_OK);
        Result := False;
        Exit;
      end;
      
      if ExitCode <> 0 then
      begin
        DownloadProgressPage.Hide;
        MsgBox(Format('Ошибка распаковки архива. Код выхода PowerShell: %d', [ExitCode]), mbError, MB_OK);
        Result := False;
        Exit;
      end;
      
      DownloadProgressPage.SetProgress(100, 100);
      
      // Проверка что исполняемый файл существует после распаковки
      if not FileExists(ExpandConstant('{app}\{#AppName}.exe')) then
      begin
        DownloadProgressPage.Hide;
        MsgBox(Format('Ошибка: после распаковки не найден файл %s', [ExpandConstant('{app}\{#AppName}.exe')]), mbError, MB_OK);
        Result := False;
        Exit;
      end;
      
      Log('Archive downloaded and extracted successfully');
    finally
      DownloadProgressPage.Hide;
      
      // Очистка временного файла
      if FileExists(ZipPath) then
      begin
        try
          DeleteFile(ZipPath);
        except
          // Игнорируем ошибки при удалении
        end;
      end;
    end;
  end;
end;

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

