; Inno Setup Script for Tf2SkinGenerator
; Bootstrap installer that downloads the full package from GitHub Releases

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
; Изменяем иконку только если файл существует (вручную или через препроцессор)
; SetupIconFile=assets\icon.ico
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

[Files]
; ВАЖНО: Для использования IDP версии нужен idp.dll в папке installer/
; Если idp.dll недоступен, используйте Tf2SkinGenerator-no-IDP.iss вместо этого файла
; Source: "idp.dll"; DestDir: "{tmp}"; Flags: dontcopy nocompression

[Code]
var
  DownloadPage: TDownloadWizardPage;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if Progress = ProgressMax then
    Log(Format('Successfully downloaded %s', [FileName]));
  Result := True;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard();
begin
  // ВАЖНО: Убедитесь, что idp.dll находится в папке installer/ перед сборкой
  // Если idp.dll недоступен, используйте Tf2SkinGenerator-no-IDP.iss
  ExtractTemporaryFile('idp.dll');
  
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), @OnDownloadProgress);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ZipPath: String;
  UnzipCommand: String;
  UnzipArgs: String;
  ExitCode: Integer;
begin
  Result := True;
  
  if CurPageID = wpReady then
  begin
    DownloadPage.Clear;
    DownloadPage.Add({#DownloadURL}, '{#AssetName}', '');
    
    try
      try
        DownloadPage.Show;
        try
          if DownloadPage.Download then
          begin
            // Скачивание успешно
            ZipPath := ExpandConstant('{tmp}\{#AssetName}');
            
            // Проверка что файл скачан
            if not FileExists(ZipPath) then
            begin
              MsgBox('Ошибка: скачанный файл не найден: ' + ZipPath, mbError, MB_OK);
              Result := False;
              Exit;
            end;
            
            // Распаковка через PowerShell Expand-Archive
            // Сначала распаковываем во временную папку, затем перемещаем содержимое
            UnzipCommand := 'powershell.exe';
            UnzipArgs := Format('-NoProfile -ExecutionPolicy Bypass -Command "$tmpDir = Join-Path $env:TEMP ''Tf2SkinGenerator-install''; if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }; Expand-Archive -Path ''%s'' -DestinationPath $tmpDir -Force; $sourceDir = Join-Path $tmpDir ''Tf2SkinGenerator''; if (Test-Path $sourceDir) { Copy-Item -Path ''$sourceDir\*'' -Destination ''%s'' -Recurse -Force; Remove-Item -Recurse -Force $tmpDir } else { Copy-Item -Path ''$tmpDir\*'' -Destination ''%s'' -Recurse -Force; Remove-Item -Recurse -Force $tmpDir }"', [
              ZipPath,
              ExpandConstant('{app}'),
              ExpandConstant('{app}')
            ]);
            
            Log('Extracting archive with PowerShell...');
            Log('Command: ' + UnzipCommand);
            Log('Args: ' + UnzipArgs);
            
            if not Exec(UnzipCommand, UnzipArgs, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
            begin
              MsgBox('Ошибка при запуске PowerShell для распаковки архива.', mbError, MB_OK);
              Result := False;
              Exit;
            end;
            
            if ExitCode <> 0 then
            begin
              MsgBox(Format('Ошибка распаковки архива. Код выхода PowerShell: %d', [ExitCode]), mbError, MB_OK);
              Result := False;
              Exit;
            end;
            
            // Проверка что исполняемый файл существует после распаковки
            if not FileExists(ExpandConstant('{app}\{#AppName}.exe')) then
            begin
              MsgBox(Format('Ошибка: после распаковки не найден файл %s', [ExpandConstant('{app}\{#AppName}.exe')]), mbError, MB_OK);
              Result := False;
              Exit;
            end;
            
            Log('Archive extracted successfully');
          end
          else
          begin
            // Скачивание не удалось
            MsgBox('Ошибка при скачивании файла. Пожалуйста, проверьте подключение к интернету и попробуйте снова.', mbError, MB_OK);
            Result := False;
            Exit;
          end;
        finally
          DownloadPage.Hide;
        end;
      except
        MsgBox('Ошибка при скачивании или распаковке файла: ' + GetExceptionMessage, mbError, MB_OK);
        Result := False;
        Exit;
      end;
    finally
      // Очистка временного файла
      if FileExists(ExpandConstant('{tmp}\{#AssetName}')) then
      begin
        DeleteFile(ExpandConstant('{tmp}\{#AssetName}'));
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

