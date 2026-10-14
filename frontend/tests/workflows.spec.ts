import{test,expect}from'@playwright/test';
test.beforeEach(async({request})=>{await request.post('/api/v1/demo/reset')});
test('operator can complete a full incident lifecycle',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:/بحرانی.*ورود به محدوده حفاظت‌شده/}).click();
 await page.getByRole('button',{name:'تأیید حادثه',exact:true}).click();
 await page.getByRole('button',{name:'تأیید و اعزام گشت',exact:true}).click();
 await page.getByRole('button',{name:'ثبت حرکت گشت',exact:true}).click();
 await page.getByRole('button',{name:'ثبت حضور در محل',exact:true}).click();
 await expect(page.getByRole('button',{name:'ثبت گزارش و خاتمه',exact:true})).toBeDisabled();
 await page.getByLabel('گزارش خاتمه (الزامی)').fill('بازرسی نمایشی تکمیل شد.');
 await page.getByRole('button',{name:'ثبت گزارش و خاتمه',exact:true}).click();
 await expect(page.locator('dialog .detail-tags')).toContainText('خاتمه‌یافته');
});
test('device command gets an execution acknowledgement',async({page})=>{
 await page.goto('/#assets');
 const row=page.getByRole('row').filter({hasText:'AST-001'});
 await row.getByRole('button',{name:/مشاهده و فرمان/}).click();
 await page.getByRole('button',{name:'بررسی و ارسال فرمان',exact:true}).click();
 await page.getByRole('button',{name:'تأیید ارسال',exact:true}).click();
 await expect(page.locator('dialog')).toContainText('اجراشده',{timeout:15000});
});
test('responsive shell avoids horizontal page overflow',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.goto('/');
 await expect(page.getByRole('heading',{name:'مرکز فرماندهی',exact:true})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
});
