import { getPrivacyInfo } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useAsync } from "../components/ui";

// Plain-language notice. It describes what the code actually does; have it
// reviewed by your institution before relying on it as a legal document.
const TEXT = {
  en: (days) => [
    ["Who runs this", "TrayTrack is run by your college's mess administration to monitor food safety in its mess halls."],
    ["What we collect", "When you sign in with your college Google account we receive your email address and name. With each report we store the mess hall, category, meal, dish, your description, an optional photo, and the time. With a meal rating we store the hall, meal, stars, an optional comment and the date."],
    ["Why", "To verify that reports come from real students of the college, to stop one person flooding the system, to detect patterns of food-safety problems, to let you follow up on your own reports, and to tell the responsible authority (Mess Head, Principal, FSSAI contact) when there is a confirmed problem."],
    ["Who sees what", "The public dashboard shows only counts, alert levels and statuses — never your identity or your words. College staff see your report with your email masked (e.g. ra*****@college.edu), or 'Anonymous student' if you chose to hide your identity. Photos are visible only to signed-in staff of your college. Location data in photos is removed when you upload them."],
    ["How long", `Your email, name, description and photos are removed from your reports automatically after ${days} days. Counts by hall, category and date are kept so history stays accurate.`],
    ["Your rights", "From My reports you can download everything you've submitted, or delete your data at any time. Deleting removes your identity, descriptions and photos from all your reports and ratings; it can't be undone."],
    ["Contact", "Questions or concerns: contact your college's mess committee or grievance officer."],
  ],
  hi: (days) => [
    ["इसे कौन चलाता है", "TrayTrack आपके कॉलेज के मेस प्रशासन द्वारा मेस हॉल में खाद्य सुरक्षा की निगरानी के लिए चलाया जाता है।"],
    ["हम क्या जानकारी लेते हैं", "जब आप अपने कॉलेज Google खाते से साइन इन करते हैं तो हमें आपका ईमेल और नाम मिलता है। हर शिकायत के साथ हम मेस हॉल, श्रेणी, भोजन, व्यंजन, आपका विवरण, वैकल्पिक फ़ोटो और समय रखते हैं। रेटिंग के साथ हम हॉल, भोजन, स्टार, वैकल्पिक टिप्पणी और तारीख रखते हैं।"],
    ["क्यों", "यह जाँचने के लिए कि शिकायतें कॉलेज के असली छात्रों से हैं, किसी एक व्यक्ति को बहुत सारी शिकायतें भेजने से रोकने के लिए, खाद्य सुरक्षा समस्याओं के पैटर्न पहचानने के लिए, आपको अपनी शिकायतों पर फॉलो-अप करने देने के लिए, और पुष्टि होने पर ज़िम्मेदार अधिकारी (मेस प्रमुख, प्रिंसिपल, FSSAI संपर्क) को सूचित करने के लिए।"],
    ["कौन क्या देखता है", "सार्वजनिक डैशबोर्ड पर केवल गिनती, अलर्ट स्तर और स्थिति दिखती है — आपकी पहचान या आपके शब्द कभी नहीं। कॉलेज स्टाफ को आपकी शिकायत छिपे हुए ईमेल (जैसे ra*****@college.edu) के साथ दिखती है, या 'गुमनाम छात्र' अगर आपने पहचान छिपाना चुना। फ़ोटो केवल आपके कॉलेज के साइन-इन स्टाफ को दिखती हैं। अपलोड करते समय फ़ोटो से लोकेशन जानकारी हटा दी जाती है।"],
    ["कब तक", `${days} दिनों के बाद आपका ईमेल, नाम, विवरण और फ़ोटो आपकी शिकायतों से अपने आप हटा दिए जाते हैं। हॉल, श्रेणी और तारीख के अनुसार गिनती रखी जाती है ताकि इतिहास सही रहे।`],
    ["आपके अधिकार", "'मेरी शिकायतें' से आप अपना सारा जमा किया गया डेटा डाउनलोड कर सकते हैं, या कभी भी अपना डेटा हटा सकते हैं। हटाने से आपकी सभी शिकायतों और रेटिंग से आपकी पहचान, विवरण और फ़ोटो हट जाते हैं; इसे वापस नहीं किया जा सकता।"],
    ["संपर्क", "प्रश्न या चिंता होने पर अपनी कॉलेज मेस समिति या शिकायत अधिकारी से संपर्क करें।"],
  ],
};

export default function Privacy() {
  const { t, lang } = useI18n();
  const info = useAsync(getPrivacyInfo, []);
  const days = info.data?.retention_days ?? 365;
  return (
    <div className="content">
      <h1>{t("privacy.title")}</h1>
      {info.data && <p className="hint">Version {info.data.version}</p>}
      {(TEXT[lang] || TEXT.en)(days).map(([h, p]) => (
        <section key={h}>
          <h2 className="h3">{h}</h2>
          <p>{p}</p>
        </section>
      ))}
    </div>
  );
}
